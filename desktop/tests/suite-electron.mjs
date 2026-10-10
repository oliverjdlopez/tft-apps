/** Opt-in real application smoke using fresh suite-local VOD data and no RDS. */
import { app, BrowserWindow } from "electron";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import net from "node:net";
import { once } from "node:events";
import { DesktopRuntime } from "../runtime.mjs";
import { VideoRuntime } from "../video-runtime.mjs";
import { DesktopWorkspace } from "../workspace.mjs";
import { launchOptions } from "../utils.mjs";
import { launcherPaths } from "../paths.mjs";

const roots = launcherPaths();
const temporary = await mkdtemp(path.join(roots.suite, ".migration/desktop-smoke-"));
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

const options = launchOptions(["--startup-timeout", "180", ...(disposablePorts ? ["--port", String(await freePort())] : [])], roots.suite);
const chat = new DesktopRuntime(roots.suite, process.env.CHATTFT_DESKTOP_NODE || "/usr/bin/node", options);
const video = new VideoRuntime(roots.suite, process.env.CHATTFT_DESKTOP_NODE || "/usr/bin/node", options);
if (disposablePorts) { video.backendPort = await freePort(); video.frontendPort = await freePort(); }
let window;
let workspace;
let cleanup;

/** Stop owned application processes once and remove only the disposable smoke state. */
async function stop() {
  cleanup ??= Promise.all([chat.stop(), video.stop()]).then(() => rm(temporary, { recursive: true, force: true }));
  return cleanup;
}

/** Load every product view with owned containers and sandboxed renderers. */
async function run() {
  await app.whenReady();
  const videoStart = video.start();
  assert.equal(videoStart, video.start(), "concurrent requests share one startup");
  const [origin] = await Promise.all([chat.start(), videoStart]);
  assert.equal(video.children.length, 1);
  window = new BrowserWindow({ show: false, width: 1440, height: 960, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false,
    preload: fileURLToPath(new URL("../workspace-preload.cjs", import.meta.url)),
  } });
  workspace = new DesktopWorkspace(window, () => {}, () => videoStart);
  workspace.compositionsEnabled = true;
  if (disposablePorts) {
    workspace.pages.get("vod").url = `http://127.0.0.1:${video.frontendPort}`;
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
  }
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
