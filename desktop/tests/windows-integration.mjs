/** Opt-in native Windows-to-WSL lifecycle check using the real Vite/Uvicorn workers. */
import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { createInterface } from "node:readline";
import { DesktopRuntime } from "../runtime.mjs";
import { abortable } from "../utils.mjs";

/** Replace only the backend application with a credential-free ASGI fixture. */
class FixtureRuntime extends DesktopRuntime {
  /** Run the real launcher while avoiding database and model calls during testing. */
  spawn(command, args, label, finite) {
    if (label === "Python backend") args = ["-u", `${this.root}/desktop/tests/fixtures/backend.py`, String(this.options.port)];
    return super.spawn(command, args, label, finite);
  }
}

/** Reserve an available Windows port for a test, releasing it before WSL binds. */
async function freePort() {
  const server = http.createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

/**
 * Verify both modes and cross-boundary disconnect using caller-supplied WSL paths.
 * Args:
 *   context: Distribution, user, Linux root/Node/Python and service environment.
 */
async function main(context) {
  assert.equal(process.platform, "win32", "Run with Windows node.exe");
  context.python = context.options.python;
  for (const mode of ["production", "dev"]) {
    const options = { mode, python: context.python, port: await freePort(), devPort: await freePort(), startupTimeout: 60000 };
    const runtime = new FixtureRuntime(context.root, context.node, options, context);
    try {
      const url = await runtime.start();
      const html = await (await fetch(url)).text();
      if (mode === "dev") assert.match(html, /\/@vite\/client/);
      else assert.equal(html, "{}");
      const backend = runtime.children.find((child) => child.label === "Python backend");
      // Ending only the Windows pipe exercises EOF transmission through wsl.exe;
      // an explicit shutdown command is intentionally absent in this case.
      runtime.once("failure", () => {});
      backend.child.stdin.end();
      assert.equal((await abortable(backend.finished, AbortSignal.timeout(18000))).code, 0);
      console.log(`${mode}: Windows readiness, WSL services, and parent EOF passed`);
    } finally { await runtime.stop(); }
    await assert.rejects(fetch(`http://127.0.0.1:${options.port}`));
    if (mode === "dev") await assert.rejects(fetch(`http://127.0.0.1:${options.devPort}`));
  }
  const disconnected = new FixtureRuntime(context.root, context.node, {
    mode: "dev", python: context.python, port: await freePort(), devPort: await freePort(), startupTimeout: 60000,
  }, context);
  try {
    await disconnected.start();
    disconnected.once("failure", () => {});
    const backend = disconnected.children.find((child) => child.label === "Python backend");
    backend.child.kill("SIGKILL");
    await abortable(backend.finished, AbortSignal.timeout(5000));
    const deadline = Date.now() + 16000;
    let running = true;
    while (running && Date.now() < deadline) {
      try { await fetch(`http://127.0.0.1:${disconnected.options.port}`); }
      catch { running = false; }
      if (running) await new Promise((resolve) => setTimeout(resolve, 200));
    }
    assert.equal(running, false, "Backend survived loss of its Windows wsl.exe parent");
    console.log("Abrupt Windows wsl.exe termination also stops its Linux backend");
  } finally { await disconnected.stop(); }
  // NAT WSL and Windows can bind the same numeric port independently. Windows
  // must reject its own unrelated listener rather than display the wrong app.
  const other = http.createServer((_request, response) => response.end("unrelated"));
  other.listen(0, "127.0.0.1");
  await once(other, "listening");
  const options = { mode: "dev", python: context.python, port: other.address().port, devPort: await freePort(), startupTimeout: 15000 };
  const runtime = new FixtureRuntime(context.root, context.node, options, context);
  try {
    await assert.rejects(runtime.start(), /different server|Cannot bind backend port/);
    assert.equal(await (await fetch(`http://127.0.0.1:${options.port}`)).text(), "unrelated");
    console.log("Windows port collision rejected without stopping the other service");
  } finally {
    await runtime.stop();
    other.closeAllConnections();
    await new Promise((resolve) => other.close(resolve));
  }
}

const parent = createInterface({ input: process.stdin });
parent.once("line", (line) => {
  parent.close();
  process.stdin.destroy();
  main(JSON.parse(line)).catch((error) => { console.error(error); process.exitCode = 1; });
});
