/** Verify the actual checkout Vite worker and its desktop-specific proxy overrides. */
import assert from "node:assert/strict";
import { once } from "node:events";
import http from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";
import test from "node:test";
import { abortable, ownedProcess, stopProcess, waitForHttp, waitForIdentity, waitForRecord } from "../utils.mjs";

const root = fileURLToPath(new URL("../../", import.meta.url));
const worker = path.join(root, "desktop/frontend.mjs");

test("production worker builds the existing frontend without application edits", async (t) => {
  const child = ownedProcess(process.execPath, [worker, "production"], { cwd: os.tmpdir(), label: "Vite build" });
  t.after(() => stopProcess(child, 100));
  const result = await abortable(child.finished, AbortSignal.timeout(30000));
  assert.equal(result.code, 0);
  const html = await readFile(path.join(root, "tft-chat/app/frontend/dist/index.html"), "utf8");
  assert.match(html, /\/assets\//);
  assert.doesNotMatch(html, /\/@vite\/client/);
});

test("development worker proxies API requests to the actual backend override", async (t) => {
  const backend = http.createServer((request, response) => response.end(`proxied:${request.url}`));
  backend.listen(0, "127.0.0.1");
  await once(backend, "listening");
  t.after(() => { backend.closeAllConnections(); backend.close(); });
  const reservation = http.createServer();
  reservation.listen(0, "127.0.0.1");
  await once(reservation, "listening");
  const port = reservation.address().port;
  await new Promise((resolve) => reservation.close(resolve));
  const child = ownedProcess(process.execPath, [worker, "dev", String(port), String(backend.address().port)], {
    cwd: root, label: "Vite dev", env: { ...process.env, CHATTFT_DESKTOP_IDENTITY: "vite-owned-identity" },
  });
  t.after(() => stopProcess(child));
  await waitForRecord(child, "listening", AbortSignal.timeout(15000));
  const url = `http://127.0.0.1:${port}`;
  await waitForHttp(url, AbortSignal.timeout(5000));
  await waitForIdentity(url, "vite-owned-identity", AbortSignal.timeout(5000));
  assert.match(await (await fetch(url)).text(), /\/@vite\/client/);
  for (const route of ["/api/config", "/static/test"]) {
    assert.equal(await (await fetch(`${url}${route}`)).text(), `proxied:${route}`);
  }
});

test("development worker refuses to silently switch an occupied frontend port", async (t) => {
  const other = http.createServer((_request, response) => response.end("other"));
  other.listen(0, "127.0.0.1");
  await once(other, "listening");
  t.after(() => { other.closeAllConnections(); other.close(); });
  const port = other.address().port;
  const child = ownedProcess(process.execPath, [worker, "dev", String(port), "8300"], { cwd: root, label: "Vite conflict" });
  t.after(() => stopProcess(child, 100));
  const result = await abortable(child.finished, AbortSignal.timeout(15000));
  assert.notEqual(result.code, 0);
  assert.equal(child.records.has("listening"), false);
  assert.equal(await (await fetch(`http://127.0.0.1:${port}`)).text(), "other");
});
