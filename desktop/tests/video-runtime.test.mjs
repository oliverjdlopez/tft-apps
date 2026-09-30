/** Verify attach-or-start video lifecycle using actual isolated service processes. */
import assert from "node:assert/strict";
import http from "node:http";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { VideoRuntime } from "../video-runtime.mjs";
const root = fileURLToPath(new URL("../../", import.meta.url));
const fixture = fileURLToPath(new URL("./fixtures/video-service.mjs", import.meta.url));
const schema = { info: { title: "Framewise Video Analysis and Annotation" }, paths: {
  "/api/health": { get: {} }, "/api/videos": { get: {} },
} };

/** Replace heavyweight video services with real, lightweight owned child processes. */
class FixtureRuntime extends VideoRuntime {
  /** Substitute only executables, retaining real startup, cleanup and verification. */
  spawn(_command, _args, label) {
    const kind = label.endsWith("backend") ? "backend" : "frontend";
    return super.spawn(process.execPath, [fixture, kind, String(kind === "backend" ? this.backendPort : this.frontendPort)], label);
  }
}

/** Reserve a test port with an externally owned compatible or unrelated HTTP service. */
async function external(t, body) {
  const server = http.createServer((_request, response) => {
    response.setHeader("content-type", "application/json");
    response.end(JSON.stringify(body));
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  t.after(() => { server.closeAllConnections(); server.close(); });
  return { server, port };
}

/** Allocate ephemeral ports and a fresh video runtime for each ownership scenario. */
async function setup(t, keepBackend, keepFrontend) {
  const backend = await external(t, schema);
  const frontend = await external(t, { app: "vod", backendPort: 8000 });
  if (!keepBackend) await new Promise((resolve) => backend.server.close(resolve));
  if (!keepFrontend) await new Promise((resolve) => frontend.server.close(resolve));
  const runtime = new FixtureRuntime(root, process.execPath, { startupTimeout: 5000 }, undefined, "vod");
  runtime.backendPort = backend.port;
  runtime.frontendPort = frontend.port;
  t.after(() => runtime.stop());
  return runtime;
}

for (const [backend, frontend] of [[true, true], [true, false], [false, true]]) {
  test(`occupied backend=${backend}, frontend=${frontend} rejects compatible original services`, async (t) => {
    const runtime = await setup(t, backend, frontend);
    await assert.rejects(runtime.start(), /occupied/);
    assert.equal(runtime.children.length, 0);
    if (backend) assert.equal((await fetch(`http://127.0.0.1:${runtime.backendPort}`)).status, 200);
    if (frontend) assert.equal((await fetch(`http://127.0.0.1:${runtime.frontendPort}`)).status, 200);
  });
}

test("concurrent VOD and Wisps requests share one owned pair and idempotent shutdown", async (t) => {
  const runtime = await setup(t, false, false);
  const vod = runtime.start();
  const wisps = runtime.start();
  assert.equal(vod, wisps);
  assert.equal(await vod, await wisps);
  assert.equal(runtime.children.length, 2);
  await Promise.all([runtime.stop(), runtime.stop()]);
  assert(runtime.children.every((child) => child.ended));
  await assert.rejects(fetch(await vod));
  const retry = await setup(t, false, false);
  await Promise.all([retry.start(), retry.start()]);
  assert.equal(retry.children.length, 2);
});

test("shutdown during startup cannot create a child after the ownership snapshot", async (t) => {
  const runtime = await setup(t, false, false);
  const starting = runtime.start();
  await runtime.stop();
  await assert.rejects(starting);
  assert.equal(runtime.children.length, 0);
});

test("frontend startup failure cleans up a newly owned backend", async (t) => {
  const runtime = await setup(t, false, false);
  const spawn = runtime.spawn.bind(runtime);
  runtime.spawn = (command, args, label) => {
    if (label.endsWith("frontend")) throw new Error("Frontend dependencies unavailable");
    return spawn(command, args, label);
  };
  await assert.rejects(runtime.start(), /Frontend dependencies/);
  assert.equal(runtime.children.length, 1);
  assert.equal(runtime.children[0].ended, true);
});
