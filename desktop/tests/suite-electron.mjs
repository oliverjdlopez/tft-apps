/** Opt-in real application smoke using fresh suite-local VOD data and no RDS. */
import { app, BrowserWindow } from "electron";
import assert from "node:assert/strict";
import { mkdtemp, rm, symlink, readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import net from "node:net";
import { once } from "node:events";
import { DesktopRuntime } from "../runtime.mjs";
import { VideoRuntime } from "../video-runtime.mjs";
import { DesktopWorkspace } from "../workspace.mjs";
import { launchOptions } from "../utils.mjs";
import { launcherPaths } from "../paths.mjs";

const checkout = launcherPaths();
const temporary = await mkdtemp(path.join(checkout.suite, ".migration/desktop-smoke-"));
// Runtime enforces <suite>/media, so use a disposable suite coordinate too.
// Only immutable application/dependency paths are linked into this fixture.
for (const name of ["desktop", "tft-chat", "vod-review"]) {
  await symlink(path.join(checkout.suite, name), path.join(temporary, name), "dir");
}
const roots = launcherPaths(temporary);
app.setPath("userData", path.join(temporary, "electron"));
app.setPath("sessionData", path.join(temporary, "electron"));
for (const prefix of ["RDS_", "RDS_EVAL_", "RDS_TEST_"]) {
  for (const name of ["HOST", "ADMIN", "DB", "PASSWORD"]) process.env[prefix + name] = "";
  process.env[prefix + "SYNC_LOCAL_IP"] = "0";
}
process.env.VOD_DATA_DIR = path.join(temporary, "vod-data");
const disposablePorts = process.argv.includes("--disposable-ports");

/** Reserve and release one ephemeral smoke port without touching existing servers. */
async function freePort() {
  const server = net.createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

/** Wait for an observable renderer/media outcome with a bounded deadline. */
async function until(predicate) {
  const deadline = Date.now() + 30000;
  while (!await predicate()) {
    if (Date.now() > deadline) throw new Error("Native renderer/media assertion timed out");
    await new Promise(resolve => setTimeout(resolve, 100));
  }
}

const options = launchOptions(["--startup-timeout", "180", ...(disposablePorts ? ["--port", String(await freePort())] : [])], roots.suite);
const chat = new DesktopRuntime(roots.suite, process.env.CHATTFT_DESKTOP_NODE || "/usr/bin/node", options);
const video = new VideoRuntime(roots.suite, process.env.CHATTFT_DESKTOP_NODE || "/usr/bin/node", options);
// Entry-point identity checks compare argv with import.meta.url; launch shell
// scripts through their real paths while keeping the runtime suite coordinate private.
chat.roots = Object.freeze({ ...chat.roots, desktop: checkout.desktop });
video.roots = Object.freeze({ ...video.roots, desktop: checkout.desktop });
if (disposablePorts) { video.backendPort = await freePort(); video.frontendPort = await freePort(); }
let window;
let workspace;
let cleanup;

/** Stop owned application processes once and remove only the disposable smoke state. */
async function stop() {
  cleanup ??= Promise.all([chat.stop(), video.stop()]).then(() => rm(temporary, { recursive: true, force: true }));
  return cleanup;
}

/** Load every product view with actual FastAPI/Vite services and sandboxed renderers. */
async function run() {
  await app.whenReady();
  const videoStart = video.start();
  assert.equal(videoStart, video.start(), "concurrent requests share one startup");
  const [origin] = await Promise.all([chat.start(), videoStart]);
  assert.equal(video.children.length, 2);
  window = new BrowserWindow({ show: false, width: 1440, height: 960, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false,
    preload: fileURLToPath(new URL("../workspace-preload.cjs", import.meta.url)),
  } });
  workspace = new DesktopWorkspace(window, () => {}, () => videoStart);
  workspace.compositionsEnabled = true;
  if (disposablePorts) {
    workspace.pages.get("vod").url = `http://127.0.0.1:${video.frontendPort}`;
    workspace.pages.get("viewer").url = `http://127.0.0.1:${video.frontendPort}/watch`;
  }
  for (const [tab, view, route] of [["chat", workspace.chat, "/"],
    ["compositions", workspace.compositions, "/compositions"], ["rolldown", workspace.rolldown, "/rolldown"],
    ["flowchart", workspace.flowchart, "/flowchart"]]) {
    await view.webContents.loadURL(new URL(route, origin).href);
    workspace.select(tab);
    const title = await view.webContents.executeJavaScript("document.title");
    assert(title.length > 0);
    assert.equal(await view.webContents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
    console.log(`PASS: ${tab} loads at ${route}`);
  }
  for (const tab of ["vod"]) {
    const page = workspace.pages.get(tab);
    await page.view.webContents.loadURL(page.url);
    workspace.select(tab);
    assert(await page.view.webContents.executeJavaScript("document.body.innerText.length > 0"));
    console.log(`PASS: ${tab} loads the round review page`);
    const source = path.join(temporary, "synthetic.mp4");
    execFileSync("ffmpeg", ["-y", "-v", "error", "-f", "lavfi", "-i", "color=s=128x96:d=5:r=10",
      "-c:v", "libx264", "-pix_fmt", "yuv420p", source], { timeout: 30000 });
    const form = new FormData();
    form.append("file", new Blob([await readFile(source)], { type: "video/mp4" }), "synthetic.mp4");
    const response = await fetch(`http://127.0.0.1:${video.backendPort}/api/videos`, { method: "POST", body: form });
    assert.equal(response.status, 201);
    const record = await response.json();
    await page.view.webContents.loadURL(page.url);
    await until(() => page.view.webContents.executeJavaScript(`!!document.querySelector('option[value="${record.id}"]')`));
    await page.view.webContents.executeJavaScript(`(() => { const select=document.querySelector('[aria-label="Recent videos"]'); select.value=${JSON.stringify(record.id)}; select.dispatchEvent(new Event('change',{bubbles:true})); })()`);
    await until(() => page.view.webContents.executeJavaScript("(() => { const video=document.querySelector('video'); return video?.readyState>=2 && video.videoWidth===128 && video.videoHeight===96; })()"));
    await page.view.webContents.executeJavaScript("document.querySelector('video').currentTime=2");
    await until(() => page.view.webContents.executeJavaScript("document.querySelector('video').currentTime>=1.9"));
    console.log("PASS: native synthetic upload, decoded playback and seek");
  }
  workspace.select("viewer");
  const viewer = workspace.pages.get("viewer");
  await until(() => viewer.view.webContents.executeJavaScript(
    "document.body.innerText.includes('No videos with saved transcripts or round transitions yet.')",
  ).catch(() => false));
  assert.equal(await viewer.view.webContents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
  console.log("PASS: Watch & Read loads and excludes the unprocessed upload");
  workspace.select("chat");
  await workspace.chat.webContents.executeJavaScript("(() => { const input=document.querySelector('textarea'); Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(input,'Native retained draft'); input.dispatchEvent(new Event('input',{bubbles:true})); })()");
  await until(() => workspace.chat.webContents.executeJavaScript("document.querySelector('.send-btn')?.disabled === false"));
  workspace.select("rolldown");
  workspace.select("chat");
  assert.equal(await workspace.chat.webContents.executeJavaScript("document.querySelector('textarea').value"), "Native retained draft");
  console.log("PASS: native view switching retains the chat draft");
  window.once("closed", () => stop().then(() => app.quit()));
  window.close();
  await stop();
  assert(chat.children.every((child) => child.ended));
  assert(video.children.every((child) => child.ended));
  for (const url of [origin, `http://127.0.0.1:${video.backendPort}/api/health`, `http://127.0.0.1:${video.frontendPort}/`]) {
    await assert.rejects(fetch(url));
  }
  console.log("PASS: closing desktop stops all owned application processes");
}

app.on("window-all-closed", () => {});
run().catch(async (error) => {
  console.error(error);
  process.exitCode = 1;
  window?.destroy();
  await stop();
  app.exit(1);
});
