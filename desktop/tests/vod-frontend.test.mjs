/** Verify standalone VOD frontends select the right backend without repo edits. */
import assert from "node:assert/strict";
import { mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { startVodFrontend } from "../vod-frontend.mjs";

test("VOD and Wisps launch with separate ports and same-origin API requests", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "vod frontend "));
  t.after(() => rm(root, { recursive: true, force: true }));
  const previousBase = process.env.VITE_API_BASE;
  t.after(() => {
    if (previousBase === undefined) delete process.env.VITE_API_BASE;
    else process.env.VITE_API_BASE = previousBase;
  });
  const moduleDir = path.join(root, "frontend/node_modules/vite/dist/node");
  await mkdir(moduleDir, { recursive: true });
  await writeFile(path.join(root, "package.json"), '{"type":"module"}');
  await writeFile(path.join(moduleDir, "index.js"), `
    export async function createServer(options) {
      return { options, async listen() { this.listening = true; }, printUrls() {} };
    }
  `);
  for (const [args, port, backend] of [[[], 5174, 8000], [["--wisps"], 5175, 8001]]) {
    process.env.VITE_API_BASE = "http://wrong-server:9999";
    const server = await startVodFrontend(["--repo", root, ...args]);
    assert.equal(server.listening, true);
    assert.equal(server.options.root, path.join(root, "frontend"));
    assert.equal(server.options.server.port, port);
    assert.equal(server.options.server.strictPort, true);
    assert.equal(server.options.server.host, "127.0.0.1");
    assert.equal(server.options.server.proxy["/api"].target, `http://127.0.0.1:${backend}`);
    assert.equal(process.env.VITE_API_BASE, "");
  }
});
