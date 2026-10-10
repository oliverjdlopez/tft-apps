/** Verify cross-OS path handling, ownership probes, and the Linux pipe guardian. */
import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import net from "node:net";
import { abortable, createParentPipe, ownedProcess, splitWslOptions, stageWindowsShell, stopProcess, waitForIdentity, waitForRecord, wslCommand } from "../utils.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const worker = path.join(root, "desktop/wsl-worker.mjs");
const fixture = path.join(root, "desktop/tests/fixtures/service.mjs");

test("GUI lifetime pipe delivers shutdown even if quit precedes Electron connection", async (t) => {
  const lifetime = await createParentPipe();
  t.after(() => lifetime.close());
  lifetime.shutdown();
  const client = net.createConnection(lifetime.name);
  t.after(() => client.destroy());
  const [data] = await once(client, "data");
  assert.equal(data.toString(), "shutdown\n");
});

test("GUI lifetime pipe disconnects when the bootstrap disappears", async (t) => {
  const lifetime = await createParentPipe();
  const client = net.createConnection(lifetime.name);
  t.after(() => client.destroy());
  await once(client, "connect");
  const closed = once(client, "close");
  lifetime.close();
  await abortable(closed, AbortSignal.timeout(2000));
});

test("WSL options preserve application options and reject ambiguous Windows paths", () => {
  assert.deepEqual(splitWslOptions(["--mode", "dev", "--windows-node", "/mnt/c/Node JS/node.exe", "--port", "8301"]), {
    setup: false, windowsNode: "/mnt/c/Node JS/node.exe", applicationArgs: ["--mode", "dev", "--port", "8301"],
  });
  assert(splitWslOptions(["--setup-windows"]).setup);
  assert.throws(() => splitWslOptions(["--windows-node", "--port"]), /WSL path/);
  assert.throws(() => splitWslOptions(["--windows-node=C:\\node.exe"]), /WSL path/);
});

test("WSL commands retain distro, user, Linux paths and shell metacharacters literally", () => {
  const context = { distro: "Ubuntu Dev", user: "developer", root: "/home/dev/project ' $stuff", node: "/home/dev/node 22/bin/node" };
  assert.deepEqual(wslCommand(context), {
    command: "wsl.exe", args: ["--distribution", context.distro, "--user", "developer", "--cd", context.root,
      "--exec", context.node, `${context.root}/desktop/wsl-worker.mjs`],
  });
});

test("Windows staging copies shell only and source edits produce a fresh immutable directory", async (t) => {
  const cache = await mkdtemp(path.join(os.tmpdir(), "desktop windows cache "));
  t.after(() => rm(cache, { recursive: true, force: true }));
  const staged = await stageWindowsShell(path.join(root, "desktop"), cache);
  assert.equal(await stageWindowsShell(path.join(root, "desktop"), cache), staged);
  assert.match(await readFile(path.join(staged, "workspace.mjs"), "utf8"), /persist:cloudbeaver/);
  assert.match(await readFile(path.join(staged, "main.mjs"), "utf8"), /sandbox: true/);
  for (const name of ["media.mjs", "media.js"]) {
    assert.equal(await readFile(path.join(staged, name), "utf8"), await readFile(path.join(root, "desktop", name), "utf8"));
  }
  await assert.rejects(readFile(path.join(staged, "backend.py")), { code: "ENOENT" });
  await writeFile(path.join(staged, "status.css"), "new style");
  const updated = await stageWindowsShell(staged, cache);
  assert.notEqual(updated, staged);
});

test("identity probes reject an unrelated Windows service even when it returns HTTP 200", async (t) => {
  let identity = "owned";
  const other = http.createServer((_request, response) => {
    response.setHeader("x-chattft-desktop-identity", identity);
    response.end("healthy");
  });
  other.listen(0, "127.0.0.1");
  await once(other, "listening");
  t.after(() => { other.closeAllConnections(); other.close(); });
  const origin = `http://127.0.0.1:${other.address().port}`;
  await waitForIdentity(origin, "owned", AbortSignal.timeout(2000));
  identity = "someone-else";
  await assert.rejects(waitForIdentity(origin, "owned", AbortSignal.timeout(2000)), /different server on Windows/);
  assert.equal((await fetch(origin)).status, 200);
});

for (const shutdown of ["command", "disconnect"]) {
  test(`Linux guardian shuts down its service on parent ${shutdown}`, { skip: process.platform === "win32" }, async (t) => {
    const handle = ownedProcess(process.execPath, [worker], { cwd: root, label: "WSL guardian" });
    t.after(() => stopProcess(handle));
    handle.child.stdin.write(`${JSON.stringify({ command: process.execPath, args: [fixture, "backend"], env: process.env })}\n`);
    const bound = await waitForRecord(handle, "bound", AbortSignal.timeout(5000));
    assert.equal((await fetch(`http://127.0.0.1:${bound.port}`)).status, 200);
    handle.child.stdin.end(shutdown === "command" ? "shutdown\n" : "");
    assert.equal((await abortable(handle.finished, AbortSignal.timeout(5000))).code, 0);
    await assert.rejects(fetch(`http://127.0.0.1:${bound.port}`));
  });
}

test("Linux guardian reports missing executables and exits without hanging", { skip: process.platform === "win32" }, async (t) => {
  const handle = ownedProcess(process.execPath, [worker], { cwd: root, label: "WSL guardian" });
  t.after(() => stopProcess(handle));
  handle.child.stdin.write(`${JSON.stringify({ command: "/does/not/exist", args: [], env: process.env })}\n`);
  assert.equal((await abortable(handle.finished, AbortSignal.timeout(5000))).code, 1);
  assert.match(handle.records.get("error").message, /WSL container worker/);
});

test("Linux guardian bounds shutdown when a service ignores stdin", { skip: process.platform === "win32", timeout: 55000 }, async (t) => {
  const handle = ownedProcess(process.execPath, [worker], { cwd: root, label: "stuck WSL service" });
  t.after(() => stopProcess(handle));
  handle.child.stdin.write(`${JSON.stringify({ command: process.execPath, args: ["-e", "setInterval(() => {}, 1000)"], env: process.env })}\n`);
  handle.child.stdin.end();
  assert.equal((await abortable(handle.finished, AbortSignal.timeout(50000))).code, 1);
});

test("Linux guardian forwards the selected application cwd and private environment", { skip: process.platform === "win32" }, async (t) => {
  const cwd = await mkdtemp(path.join(os.tmpdir(), "suite WSL cwd "));
  t.after(() => rm(cwd, { recursive: true, force: true }));
  const handle = ownedProcess(process.execPath, [worker], { cwd: root, label: "WSL environment fixture" });
  t.after(() => stopProcess(handle));
  const script = 'console.log("CHAT_TFT_DESKTOP " + JSON.stringify({type:"context",cwd:process.cwd(),value:process.env.SUITE_FIXTURE_VALUE})); process.stdin.on("end",()=>process.exit(0)); process.stdin.resume();';
  handle.child.stdin.write(`${JSON.stringify({ command: process.execPath, args: ["-e", script], cwd,
    env: { ...process.env, SUITE_FIXTURE_VALUE: "literal $value ' with spaces" } })}\n`);
  const context = await waitForRecord(handle, "context", AbortSignal.timeout(5000));
  assert.equal(context.cwd, cwd);
  assert.equal(context.value, "literal $value ' with spaces");
  handle.child.stdin.end();
  assert.equal((await abortable(handle.finished, AbortSignal.timeout(5000))).code, 0);
});
