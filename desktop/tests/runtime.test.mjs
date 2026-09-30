/** Exercise the supervisor with actual child lifetimes and isolated HTTP fixtures. */
import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, mkdir, copyFile, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { DesktopRuntime } from "../runtime.mjs";

const fixture = fileURLToPath(new URL("./fixtures/service.mjs", import.meta.url));

/** Use an HTTP fixture in place of Python while retaining real process supervision. */
class FixtureRuntime extends DesktopRuntime {
  /** Substitute only the backend executable; frontend is an isolated checkout fixture. */
  spawn(command, args, label, finite) {
    if (label === "Python backend") return super.spawn(process.execPath, [fixture, "backend", ...args.slice(2)], label, finite);
    return super.spawn(command, args, label, finite);
  }
}

/** Create a checkout with spaces to catch shell-dependent argument handling. */
async function checkout(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "chattft desktop test "));
  await mkdir(path.join(root, "desktop"));
  await copyFile(fixture, path.join(root, "desktop/frontend.mjs"));
  t.after(() => rm(root, { recursive: true, force: true }));
  return root;
}

/** Reserve a temporary unused port for a strict-port fixture. */
async function freePort() {
  const server = http.createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

for (const mode of ["production", "dev"]) {
  test(`${mode} startup waits for owned services and stops every child`, async (t) => {
    const root = await checkout(t);
    const runtime = new FixtureRuntime(root, process.execPath, { mode, startupTimeout: 5000, devPort: await freePort() });
    t.after(() => runtime.stop());
    const url = await runtime.start();
    assert.equal((await fetch(url)).status, 200);
    assert.equal(runtime.state, "running");
    assert.equal(runtime.children.length, 2);
    await runtime.stop();
    assert(runtime.children.every((child) => child.ended));
    assert.equal(runtime.state, "stopped");
  });
}

test("build failure prevents backend launch and permits a fresh retry", async (t) => {
  const root = await checkout(t);
  await writeFile(path.join(root, "fail-build"), "");
  const options = { mode: "production", startupTimeout: 5000 };
  const failed = new FixtureRuntime(root, process.execPath, options);
  await assert.rejects(failed.start(), /Frontend build/);
  assert.equal(failed.children.length, 1);
  assert(failed.children.every((child) => child.ended));
  await rm(path.join(root, "fail-build"));
  const retry = new FixtureRuntime(root, process.execPath, options);
  t.after(() => retry.stop());
  await retry.start();
  assert.equal(retry.state, "running");
});

test("an occupied backend port never attaches to or stops the other server", async (t) => {
  const root = await checkout(t);
  const other = http.createServer((_request, response) => response.end("other"));
  other.listen(0, "127.0.0.1");
  await once(other, "listening");
  t.after(() => { other.closeAllConnections(); other.close(); });
  const port = other.address().port;
  const runtime = new FixtureRuntime(root, process.execPath, { mode: "dev", port, startupTimeout: 5000 });
  await assert.rejects(runtime.start(), /Python backend/);
  assert.equal(await (await fetch(`http://127.0.0.1:${port}`)).text(), "other");
});

test("backend exit after readiness emits failure and cleanup is idempotent", async (t) => {
  const root = await checkout(t);
  const runtime = new FixtureRuntime(root, process.execPath, { mode: "production", startupTimeout: 5000 });
  t.after(() => runtime.stop());
  await runtime.start();
  const failure = once(runtime, "failure");
  runtime.children.find((child) => child.label === "Python backend").child.kill();
  assert.match((await failure)[0].message, /Python backend/);
  await Promise.all([runtime.stop(), runtime.stop()]);
  assert(runtime.children.every((child) => child.ended));
});

test("timeout cancels a stalled frontend build and reaps the process", async (t) => {
  const root = await checkout(t);
  await writeFile(path.join(root, "desktop/frontend.mjs"), 'process.stdin.on("data", () => process.exit(0)); setInterval(() => {}, 1000);');
  const runtime = new FixtureRuntime(root, process.execPath, { mode: "production", startupTimeout: 200 });
  await assert.rejects(runtime.start(), /Startup timed out/);
  assert(runtime.children.every((child) => child.ended));
});

test("shutdown prevents a late startup continuation from creating a new child", async (t) => {
  const root = await checkout(t);
  const runtime = new FixtureRuntime(root, process.execPath, { mode: "dev", startupTimeout: 5000 });
  await runtime.stop();
  assert.throws(() => runtime.spawn(process.execPath, [fixture, "backend"], "Python backend"), /shutting down/);
  assert.equal(runtime.children.length, 0);
});
