/** Opt-in real YouTube embed smoke in the desktop VOD partition; backend is mocked. */
import { app, BrowserWindow, session, net } from "electron";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { DesktopWorkspace } from "../workspace.mjs";

const root = fileURLToPath(new URL("../../vod-review/frontend/dist/", import.meta.url));
const profile = mkdtempSync(path.join(tmpdir(), "online-vod-electron-"));
app.setPath("userData", profile);
app.setPath("sessionData", profile);
app.on("window-all-closed", () => {});
const round = { timestamp_seconds: 20, scheduled_timestamp_seconds: 20, timing_error_ms: 0, class_label: "21", confidence: 1 };
const job = { id: "fixture", status: "completed", strategy: "online", results: [round], sample_interval_seconds: 10 };
const review = { id: "embed-smoke", original_name: "Public YouTube embed smoke", mode: "online", source_id: "aqz-KE-bpKQ", source_url: "https://www.youtube.com/watch?v=aqz-KE-bpKQ", source_start_seconds: 0, duration: 60, width: 1280, height: 720, local_available: false, box: { x: .1, y: .1, width: .2, height: .1, frame_time: 0 }, current_job: job, latest_job: job, active_job: null };

/** Wait for actual renderer/player readiness without indefinite network waits. */
async function until(predicate, timeout = 40000) {
  const deadline = Date.now() + timeout;
  while (!await predicate()) {
    if (Date.now() > deadline) throw new Error("YouTube embed smoke timed out");
    await delay(200);
  }
}

/** Start asynchronously so ESM module loading does not block Electron's ready event. */
async function run() {
let server, window, workspace, contents;
let stage = "startup";
try {
  await app.whenReady();
  server = createServer((request, response) => {
    const relative = decodeURIComponent(new URL(request.url, "http://fixture").pathname);
    const file = path.resolve(root, relative === "/" ? "index.html" : "." + relative);
    if (!file.startsWith(path.resolve(root) + path.sep)) { response.writeHead(404); response.end(); return; }
    try {
      response.setHeader("Content-Type", ({ ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" })[path.extname(file)] ?? "application/octet-stream");
      response.end(readFileSync(file));
    } catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const partition = session.fromPartition("persist:vod-review");
  partition.protocol.handle("http", request => {
    if (!request.url.startsWith("http://localhost:8000/")) return net.fetch(request, { bypassCustomProtocolHandlers: true });
    const url = new URL(request.url);
    const result = url.pathname === "/api/videos" ? [review] : url.pathname.endsWith("/resumable-download") || url.pathname.endsWith("/transcription") || url.pathname.endsWith("/gdrive-upload") ? null : review;
    return new Response(JSON.stringify(result), { headers: { "Content-Type": "application/json", "Access-Control-Allow-Origin": origin } });
  });
  let identified = false;
  partition.webRequest.onBeforeSendHeaders({ urls: ["https://www.youtube.com/embed/*"] }, (details, callback) => {
    const referer = Object.entries(details.requestHeaders).find(([key]) => key.toLowerCase() === "referer")?.[1];
    identified ||= typeof referer === "string" && referer.startsWith(origin);
    callback({ requestHeaders: details.requestHeaders });
  });
  window = new BrowserWindow({ show: false, width: 1440, height: 1000, webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false } });
  workspace = new DesktopWorkspace(window, () => {});
  const view = workspace.pages.get("vod").view;
  view.setBounds({ x: 0, y: 0, width: 1440, height: 1000 });
  contents = view.webContents;
  stage = "frontend load";
  await contents.loadURL(origin);
  await until(() => contents.executeJavaScript("!!document.querySelector('[aria-label=\"Recent videos\"]')"));
  stage = "review selection";
  await contents.executeJavaScript("const select=document.querySelector('[aria-label=\"Recent videos\"]');select.value='embed-smoke';select.dispatchEvent(new Event('change',{bubbles:true}));", true);
  await until(() => contents.executeJavaScript("!!document.querySelector('.youtube-player iframe')"));
  stage = "player readiness";
  const inspect = "(() => {const f=document.querySelector('.youtube-player iframe');const p=f&&window.YT?.get?.(f.id);return p?.getVideoData?.().video_id==='aqz-KE-bpKQ'})()";
  await until(() => contents.executeJavaScript(inspect).catch(() => false));
  assert.equal(identified, true, "Embed requests must identify the local frontend origin");
  stage = "round click";
  await contents.executeJavaScript("Array.from(document.querySelectorAll('.results-list button')).find(b=>b.getAttribute('role')!=='checkbox'&&/21/.test(b.textContent)).click()", true);
  stage = "round seek";
  await until(() => contents.executeJavaScript("(() => {const f=document.querySelector('.youtube-player iframe');const p=window.YT.get(f.id);return p.getCurrentTime()>=19&&p.getCurrentTime()<30})()").catch(() => false), 20000);
  assert.equal(await contents.executeJavaScript("document.querySelector('[aria-label=\"Analysis interval in seconds\"]').value"), "10");
  console.log("PASS: real Electron VOD partition, identified YouTube embed, round seek, default 10-second scan");
} catch (error) {
  console.error(`${stage}: ${String(error)}`);
  if (contents && !contents.isDestroyed()) console.error(await contents.executeJavaScript("JSON.stringify({alerts:[...document.querySelectorAll('[role=alert]')].map(e=>e.textContent),roundButtons:[...document.querySelectorAll('.results-list button')].map(e=>e.getAttribute('aria-label'))})").catch(() => "Renderer unavailable"));
  process.exitCode = 1;
} finally {
  workspace?.close();
  window?.destroy();
  await new Promise(resolve => server ? server.close(resolve) : resolve());
  rmSync(profile, { recursive: true, force: true });
  app.exit(process.exitCode ?? 0);
}
}
void run();
