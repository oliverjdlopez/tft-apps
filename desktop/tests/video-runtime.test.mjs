/** Verify VOD container ownership with actual isolated worker and HTTP lifetimes. */
import assert from "node:assert/strict";
import http from "node:http";
import { once } from "node:events";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { VideoRuntime } from "../video-runtime.mjs";
const fixture = fileURLToPath(new URL("./fixtures/container-service.mjs", import.meta.url));
const schema = { info: { title: "VOD Review and Round Classification" }, paths: {
  "/api/health": { get: {} }, "/api/videos": { get: {} },
} };

/** Substitute only the container executable, preserving real startup supervision. */
class FixtureRuntime extends VideoRuntime {
  /** Forward the exact application ports, mode and identity to the HTTP guardian. */
  spawn(_command, args, label) {
    return super.spawn(process.execPath, [fixture, ...args.slice(1)], label);
  }
}

/** Reserve a test port with an externally owned HTTP service. */
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

/** Allocate ephemeral ports and an isolated VOD checkout for an ownership scenario. */
async function setup(t, keepBackend, keepFrontend, mode = "production") {
  const root = await mkdtemp(path.join(os.tmpdir(), "vod containers test "));
  await mkdir(path.join(root, "vod-review"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const backend = await external(t, schema);
  const frontend = await external(t, { app: "vod", backendPort: 8000 });
  if (!keepBackend) await new Promise((resolve) => backend.server.close(resolve));
  if (!keepFrontend) await new Promise((resolve) => frontend.server.close(resolve));
  const runtime = new FixtureRuntime(root, process.execPath, { mode, startupTimeout: 5000 });
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

for (const mode of ["production", "dev"]) {
  test(`${mode} concurrent VOD requests share one worker and idempotent shutdown`, async (t) => {
    const runtime = await setup(t, false, false, mode);
    const vod = runtime.start();
    const secondStart = runtime.start();
    assert.equal(vod, secondStart);
    assert.equal(await vod, await secondStart);
    assert.equal(runtime.children.length, 1);
    assert.equal(runtime.service, "vod");
    assert.equal((await fetch(`http://127.0.0.1:${runtime.backendPort}/api/health`)).status, 200);
    await Promise.all([runtime.stop(), runtime.stop()]);
    assert(runtime.children.every((child) => child.ended));
    await assert.rejects(fetch(await vod));
    const retry = await setup(t, false, false, mode);
    await Promise.all([retry.start(), retry.start()]);
    assert.equal(retry.children.length, 1);
  });
}

test("shutdown during startup cannot create a child after the ownership snapshot", async (t) => {
  const runtime = await setup(t, false, false);
  const starting = runtime.start();
  await runtime.stop();
  await assert.rejects(starting);
  assert.equal(runtime.children.length, 0);
});

test("frontend startup failure cleans up the newly owned VOD worker", async (t) => {
  const runtime = await setup(t, false, false);
  await writeFile(path.join(runtime.cwd, "fail-frontend"), "");
  await assert.rejects(runtime.start(), /frontend startup failure/);
  assert.equal(runtime.children.length, 1);
  assert.equal(runtime.children[0].ended, true);
  await assert.rejects(fetch(`http://127.0.0.1:${runtime.backendPort}/api/health`));
});
