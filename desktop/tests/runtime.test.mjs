/** Exercise container supervision with actual child lifetimes and HTTP fixtures. */
import assert from "node:assert/strict";
import { once } from "node:events";
import { mkdtemp, mkdir, copyFile, rm, writeFile } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { DesktopRuntime } from "../runtime.mjs";

const fixture = fileURLToPath(new URL("./fixtures/container-service.mjs", import.meta.url));

/** Create a checkout with spaces and only a container worker, with no Python/Vite. */
async function checkout(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "chattft desktop test "));
  await mkdir(path.join(root, "desktop"));
  await mkdir(path.join(root, "tft-chat"));
  await copyFile(fixture, path.join(root, "desktop/container-worker.mjs"));
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

/** Create a runtime with isolated ports and a deliberately nonexistent Python path. */
async function runtimeFor(t, root, mode = "production") {
  const runtime = new DesktopRuntime(root, process.execPath, {
    mode, port: await freePort(), devPort: await freePort(), startupTimeout: 5000,
    python: "/missing/host/python",
  });
  t.after(() => runtime.stop());
  return runtime;
}

for (const mode of ["production", "dev"]) {
  test(`${mode} startup shares one container worker and stops both owned endpoints`, async (t) => {
    const runtime = await runtimeFor(t, await checkout(t), mode);
    const starting = runtime.start();
    assert.equal(starting, runtime.start());
    const url = await starting;
    assert.equal(url, `http://127.0.0.1:${runtime.frontendPort}`);
    assert.equal((await fetch(url)).status, 200);
    assert.equal(runtime.state, "running");
    assert.equal(runtime.children.length, 1);
    assert.match(runtime.children[0].label, /containers/);
    await runtime.stop();
    assert(runtime.children.every((child) => child.ended));
    assert.equal(runtime.state, "stopped");
    await assert.rejects(fetch(url));
    await assert.rejects(fetch(`http://127.0.0.1:${runtime.backendPort}`));
  });
}

test("container startup failure cleans up and permits a fresh retry", async (t) => {
  const root = await checkout(t);
  const marker = path.join(root, "tft-chat/fail-container");
  await writeFile(marker, "");
  const failed = await runtimeFor(t, root);
  await assert.rejects(failed.start(), /container startup failure/);
  assert.equal(failed.children.length, 1);
  assert(failed.children.every((child) => child.ended));
  await rm(marker);
  const retry = await runtimeFor(t, root);
  await retry.start();
  assert.equal(retry.state, "running");
});

for (const endpoint of ["backend", "frontend"]) {
  test(`an occupied ${endpoint} port never attaches to or stops the other server`, async (t) => {
    const runtime = await runtimeFor(t, await checkout(t), "dev");
    const other = http.createServer((_request, response) => response.end("other"));
    other.listen(runtime[`${endpoint}Port`], "127.0.0.1");
    await once(other, "listening");
    t.after(() => { other.closeAllConnections(); other.close(); });
    await assert.rejects(runtime.start(), /occupied/);
    assert.equal(runtime.children.length, 0);
    assert.equal(await (await fetch(`http://127.0.0.1:${runtime[`${endpoint}Port`]}`)).text(), "other");
  });
}

test("worker exit after readiness emits failure and cleanup is idempotent", async (t) => {
  const runtime = await runtimeFor(t, await checkout(t));
  await runtime.start();
  const failure = once(runtime, "failure");
  runtime.children[0].child.kill();
  assert.match((await failure)[0].message, /ChatTFT containers/);
  await Promise.all([runtime.stop(), runtime.stop()]);
  assert(runtime.children.every((child) => child.ended));
});

test("timeout cancels a stalled container worker and reaps the process", async (t) => {
  const root = await checkout(t);
  await writeFile(path.join(root, "tft-chat/stall-container"), "");
  const runtime = await runtimeFor(t, root);
  runtime.options.startupTimeout = 250;
  await assert.rejects(runtime.start(), /Startup timed out/);
  assert(runtime.children.every((child) => child.ended));
});

for (const [marker, message] of [["wrong-identity", /different server/],
  ["wrong-bound", /unexpected backend port/], ["wrong-listening", /unexpected frontend port/]]) {
  test(`${marker} prevents adopting a misleading worker endpoint`, async (t) => {
    const root = await checkout(t);
    await writeFile(path.join(root, "tft-chat", marker), "");
    const runtime = await runtimeFor(t, root, "dev");
    await assert.rejects(runtime.start(), message);
    assert(runtime.children.every((child) => child.ended));
  });
}

test("cleanup failure remains visible and cannot be mistaken for completed shutdown", async (t) => {
  const root = await checkout(t);
  const runtime = new DesktopRuntime(root, process.execPath, {
    mode: "production", port: await freePort(), startupTimeout: 5000,
  });
  await runtime.start();
  await writeFile(path.join(root, "tft-chat/fail-cleanup"), "");
  await assert.rejects(runtime.stop(), /could not be stopped/);
  await assert.rejects(runtime.stop(), /could not be stopped/);
  assert(runtime.children.every((child) => child.ended));
});

test("shutdown during startup prevents creating a child after the ownership snapshot", async (t) => {
  const runtime = await runtimeFor(t, await checkout(t), "dev");
  const starting = runtime.start();
  await runtime.stop();
  await assert.rejects(starting, /shutting down/);
  assert.equal(runtime.children.length, 0);
});
