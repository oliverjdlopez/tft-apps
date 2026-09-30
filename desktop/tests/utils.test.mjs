/** Verify launcher boundaries using real sockets and child processes. */
import assert from "node:assert/strict";
import http from "node:http";
import { EventEmitter, once } from "node:events";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { ensureLangfuse, launchOptions, navigationPolicy, ownedProcess, permissionAllowed, pythonExecutable, stopProcess, waitForHttp, waitForRecord, workspaceCommandAllowed } from "../utils.mjs";

const fixture = fileURLToPath(new URL("./fixtures/service.mjs", import.meta.url));

test("healthy Langfuse is reused without launching or reseeding Docker", async () => {
  let cancelled = false;
  assert.equal(await ensureLangfuse("/repo", "/repo/.venv/bin/python", {
    request: async () => ({ ok: true, body: { cancel: async () => { cancelled = true; } } }),
    runnerReady: async () => true,
    spawnProcess: () => { assert.fail("Healthy Langfuse must not be restarted"); },
    log: () => {},
  }), true);
  assert.equal(cancelled, true);
});

test("unavailable Langfuse starts through the checkout launcher and waits for completion", async () => {
  for (const unavailable of [async () => { throw new Error("ECONNREFUSED"); }, async () => ({ ok: false })]) {
    const child = new EventEmitter();
    const result = ensureLangfuse("/checkout with spaces", "/custom env/python", {
      request: unavailable, log: () => {},
      spawnProcess: (command, args, options) => {
        assert.equal(command, "/custom env/python");
        assert.deepEqual(args, ["-m", "evals", "up", "--no-browser"]);
        assert.equal(options.cwd, "/checkout with spaces");
        assert.equal(options.shell, false);
        assert.equal(options.stdio, "inherit");
        setImmediate(() => child.emit("close", 0));
        return child;
      },
    });
    assert.equal(await result, true);
  }
});

test("Docker failure or missing Python warns without preventing desktop startup", async () => {
  for (const event of ["close", "error"]) {
    const warnings = [];
    assert.equal(await ensureLangfuse("/repo", "missing-python", {
      request: async () => { throw new Error("offline"); }, log: () => {},
      warn: (message) => warnings.push(message),
      spawnProcess: () => {
        const child = new EventEmitter();
        setImmediate(() => child.emit(event, event === "close" ? 2 : new Error("ENOENT")));
        return child;
      },
    }), false);
    assert.match(warnings[0], /Ensure Docker is running/);
    assert.match(warnings[0], /Continuing ChatTFT startup/);
  }
});

test("native interpreter paths preserve spaces and Windows path semantics", () => {
  assert.equal(pythonExecutable("C:\\My Checkout", undefined, "win32"), "C:\\My Checkout\\.venv\\Scripts\\python.exe");
  assert.equal(pythonExecutable("/Users/test/My Checkout", undefined, "darwin"), "/Users/test/My Checkout/.venv/bin/python");
  assert.equal(pythonExecutable("/repo", "./env/python", "darwin", "/custom dir"), "/custom dir/env/python");
  assert.equal(pythonExecutable("/repo", "python3", "darwin"), "python3");
});

test("launch options reject invalid ports and preserve configured-port default", () => {
  const defaults = launchOptions([], "/repo");
  assert.equal(defaults.port, undefined);
  assert.equal(defaults.devPort, 5173);
  assert.equal(defaults.mode, "production");
  assert.equal(defaults.startupTimeout, 120000);
  const dev = launchOptions(["--mode", "dev", "--port", "8301", "--dev-port", "5174"], "/repo");
  assert.equal(dev.port, 8301);
  assert.equal(dev.devPort, 5174);
  for (const value of ["0", "-1", "65536", "8300junk", "1.5"]) {
    assert.throws(() => launchOptions(["--port", value], "/repo"));
  }
  assert.throws(() => launchOptions(["--mode", "other"], "/repo"));
  assert.throws(() => launchOptions(["--unknown"], "/repo"));
});

test("navigation and clipboard access are limited to the intended origins", () => {
  const origin = "http://127.0.0.1:8300";
  assert.equal(navigationPolicy(`${origin}/api/config`, origin), "internal");
  assert.equal(navigationPolicy("https://platform.openai.com/traces/trace_123", origin), "external");
  for (const url of ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "mailto:a@b.com", "https://user:password@example.com", "invalid"]) {
    assert.equal(navigationPolicy(url, origin), "blocked");
  }
  assert.equal(navigationPolicy("http://127.0.0.1:8301", origin), "external");
  assert.equal(permissionAllowed("clipboard-sanitized-write", origin, origin), true);
  assert.equal(permissionAllowed("clipboard-read", origin, origin), false);
  assert.equal(permissionAllowed("clipboard-sanitized-write", "https://example.com", origin), false);
  assert.equal(permissionAllowed("clipboard-sanitized-write", origin, origin, false), false);
});

test("workspace commands allow every shell tab, including Flowchart, and nothing else", () => {
  const contents = { mainFrame: { url: "file:///shell/workspace.html" } };
  const event = { sender: contents, senderFrame: contents.mainFrame };
  for (const action of ["chat", "rolldown", "flowchart", "compositions", "vod", "wisps", "langfuse", "database", "retry"])
    assert.equal(workspaceCommandAllowed(event, contents, contents.mainFrame.url, action), true);
  assert.equal(workspaceCommandAllowed(event, contents, contents.mainFrame.url, "devtools"), false);
  assert.equal(workspaceCommandAllowed(event, contents, "file:///other.html", "flowchart"), false);
});

test("readiness retries non-200 responses and respects cancellation", async (t) => {
  let ready = false;
  const server = http.createServer((_request, response) => { response.writeHead(ready ? 200 : 503).end(); });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  const url = `http://127.0.0.1:${server.address().port}`;
  await assert.rejects(waitForHttp(url, AbortSignal.timeout(100)));
  const timer = setTimeout(() => { ready = true; }, 50);
  t.after(() => clearTimeout(timer));
  await waitForHttp(url, AbortSignal.timeout(3000));
});

test("owned child exits gracefully over stdin and releases its socket", async (t) => {
  const child = ownedProcess(process.execPath, [fixture, "backend"], { cwd: process.cwd(), label: "fixture" });
  t.after(() => stopProcess(child, 100));
  const { port } = await waitForRecord(child, "bound", AbortSignal.timeout(5000));
  await waitForHttp(`http://127.0.0.1:${port}`, AbortSignal.timeout(5000));
  await stopProcess(child);
  assert.equal(child.result.code, 0);
  const replacement = http.createServer();
  replacement.listen(port, "127.0.0.1");
  await once(replacement, "listening");
  replacement.close();
});

test("child exits when the parent pipe closes without a shutdown command", async () => {
  const child = ownedProcess(process.execPath, [fixture, "backend"], { cwd: process.cwd(), label: "fixture" });
  await waitForRecord(child, "bound", AbortSignal.timeout(5000));
  child.child.stdin.end();
  const result = await child.finished;
  assert.equal(result.code, 0);
});

test("missing executable rejects readiness with a setup hint", async () => {
  const child = ownedProcess("chattft-nonexistent-executable-9238", [], { cwd: process.cwd(), label: "Python backend" });
  await assert.rejects(waitForRecord(child, "bound", AbortSignal.timeout(5000)), /executable was not found/);
});

test("unresponsive owned child is forcefully stopped after its grace period", async () => {
  const child = ownedProcess(process.execPath, ["-e", "setInterval(() => {}, 1000)"], { cwd: process.cwd(), label: "unresponsive fixture" });
  await stopProcess(child, 50);
  assert.equal(child.ended, true);
});

test("healthy Langfuse web with a stopped host runner invokes startup", async () => {
  let launched = false;
  assert.equal(await ensureLangfuse("/repo", "/python", {
    request: async () => ({ ok: true }), runnerReady: async () => false, log: () => {},
    spawnProcess: () => {
      launched = true;
      const child = new EventEmitter();
      setImmediate(() => child.emit("close", 0));
      return child;
    },
  }), true);
  assert.equal(launched, true);
});
