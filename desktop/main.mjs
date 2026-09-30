/** Native Electron lifecycle around the unchanged ChatTFT web application. */
import { app, BrowserWindow, dialog, Menu, session, shell } from "electron";
import { createHash } from "node:crypto";
import { mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createInterface } from "node:readline";
import net from "node:net";
import { DesktopWorkspace } from "./workspace.mjs";
import { DesktopRuntime } from "./runtime.mjs";
import { VideoRuntime } from "./video-runtime.mjs";
import { launchOptions, navigationPolicy, permissionAllowed } from "./utils.mjs";

const wsl = process.env.CHATTFT_DESKTOP_WSL ? JSON.parse(process.env.CHATTFT_DESKTOP_WSL) : undefined;
delete process.env.CHATTFT_DESKTOP_WSL;
const root = wsl?.root ?? fileURLToPath(new URL("../", import.meta.url));
const statusPath = fileURLToPath(new URL("./status.html", import.meta.url));
const options = wsl?.options ?? launchOptions(process.argv.slice(2), root);
const node = wsl?.node ?? process.env.CHATTFT_DESKTOP_NODE;
let window;
let workspace;
let runtime;
let frontendUrl;
let statusMessage = "Starting ChatTFT…";
let quitting = false;
let quitAllowed = false;
let recovering = false;
let restarting = false;
const videoRuntimes = new Map();
const videoStarts = new Map();

app.setName("ChatTFT Desktop");
// Different checkouts may run independently, but each retains a stable profile
// and single-instance lock across launches and frontend rebuilds.
const checkoutId = createHash("sha256").update(wsl ? `${wsl.distro}/${wsl.user}:${root}` : root).digest("hex").slice(0, 12);
const profilePath = path.join(app.getPath("appData"), "ChatTFT Desktop", checkoutId);
mkdirSync(profilePath, { recursive: true });
app.setPath("userData", profilePath);
app.setPath("sessionData", profilePath);

/** Create a native window with no privileged renderer bridge. */
function createWindow() {
  window = new BrowserWindow({
    title: "ChatTFT", width: 1440, height: 960, minWidth: 720, minHeight: 480,
    backgroundColor: "#fafafa", show: false,
    webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true, preload: fileURLToPath(new URL("./workspace-preload.cjs", import.meta.url)) },
  });
  workspace = new DesktopWorkspace(window, openExternal, ensureVideoWorkspace);
  for (const view of [workspace.chat, workspace.rolldown, workspace.flowchart, workspace.compositions]) {
    const contents = view.webContents;
    contents.on("will-navigate", (event) => {
      const url = event.url;
      const policy = navigationPolicy(url, frontendUrl);
      if (policy !== "internal") {
        event.preventDefault();
        if (policy === "external") openExternal(url);
      }
    });
    contents.on("will-redirect", (event) => {
      if (navigationPolicy(event.url, frontendUrl) !== "internal") event.preventDefault();
    });
    contents.setWindowOpenHandler(({ url }) => {
      const policy = navigationPolicy(url, frontendUrl);
      if (policy === "internal") contents.loadURL(url).catch(handleFailure);
      else if (policy === "external") openExternal(url);
      return { action: "deny" };
    });
    contents.on("will-attach-webview", (event) => event.preventDefault());
    contents.on("render-process-gone", () => handleFailure(new Error("The application window stopped responding. Retry to restart the desktop services.")));
    contents.on("did-fail-load", (_event, code, _description, url, mainFrame) => {
      if (code !== -3 && mainFrame && navigationPolicy(url, frontendUrl) === "internal") {
        handleFailure(new Error("The application could not be loaded. Check the launch terminal, then retry."));
      }
    });
  }
  window.on("closed", () => { window = undefined; workspace = undefined; });
  window.once("ready-to-show", () => window?.show());
  if (frontendUrl) loadApplicationViews().catch(handleFailure);
  else showStatus(statusMessage);
}

/**
 * Open only previously validated HTTP(S) links in the system browser.
 * Args:
 *   url: Destination approved by the navigation policy.
 */
function openExternal(url) {
  shell.openExternal(url).catch(() => {
    dialog.showErrorBox("Could not open browser", "Open the link using your system browser.");
  });
}

/**
 * Show local startup progress without injecting content into the application.
 * Args:
 *   message: Fixed launcher status message.
 */
function showStatus(message) {
  statusMessage = message;
  if (window && !window.isDestroyed()) {
    for (const view of [workspace.chat, workspace.rolldown, workspace.flowchart, workspace.compositions]) {
      view.webContents.loadFile(statusPath, { query: { message } }).catch((error) => {
        if (!quitting && error.code !== "ERR_ABORTED") console.error("Could not display desktop status.");
      });
    }
  }
}

/** Load both application views from the same ready backend after startup or restart. */
async function loadApplicationViews() {
  const config = await fetch(new URL("/api/config", frontendUrl)).then(response => response.json());
  workspace.compositionsEnabled = config.composition_workbench === true;
  if (!workspace.compositionsEnabled && workspace.active === "compositions") workspace.select("chat");
  workspace.layout();
  await Promise.all([
    ...(workspace.compositionsEnabled ? [workspace.compositions.webContents.loadURL(new URL("/compositions", frontendUrl).href)] : []),
    workspace.chat.webContents.loadURL(frontendUrl),
    workspace.rolldown.webContents.loadURL(new URL("/rolldown", frontendUrl).href),
    workspace.flowchart.webContents.loadURL(new URL("/flowchart", frontendUrl).href),
  ]);
}

/**
 * Attach or start one video workspace without blocking ChatTFT startup.
 * Args:
 *   tab: VOD Review or Wisps workspace identifier.
 * Returns:
 *   A shared readiness promise; repeated retry clicks cannot create duplicates.
 */
function ensureVideoWorkspace(tab) {
  if (quitting) return Promise.reject(new Error("Desktop is quitting."));
  if (videoStarts.has(tab)) return videoStarts.get(tab);
  const pending = (async () => {
    const previous = videoRuntimes.get(tab);
    if (previous?.state === "running") return;
    await previous?.stop();
    if (quitting) return;
    const service = new VideoRuntime(root, node, options, wsl, tab);
    videoRuntimes.set(tab, service);
    service.on("failure", () => { service.state = "failed"; workspace?.fail(tab); });
    await service.start();
  })().finally(() => videoStarts.delete(tab));
  videoStarts.set(tab, pending);
  return pending;
}

/** Start one runtime and replace startup status with its existing web UI. */
async function startApplication() {
  if (quitting) return;
  frontendUrl = undefined;
  showStatus("Starting ChatTFT…");
  runtime = new DesktopRuntime(root, node, options, wsl);
  runtime.on("progress", showStatus);
  runtime.on("failure", handleFailure);
  try {
    frontendUrl = await runtime.start();
    if (quitting) return;
    if (window) await loadApplicationViews();
  } catch (error) { await handleFailure(error); }
}

/**
 * Clean up a failed runtime before offering a retry of the whole startup.
 * Args:
 *   error: Credential-safe launcher error.
 */
async function handleFailure(error) {
  // A user reload or superseding navigation may cancel a load without a failure.
  if (quitting || recovering || error.code === "ERR_ABORTED" || error.errno === -3) return;
  recovering = true;
  frontendUrl = undefined;
  showStatus("ChatTFT could not continue.");
  let cleanupFailed = false;
  try { await runtime?.stop(); } catch (cleanupError) {
    cleanupFailed = true;
    error = cleanupError;
  }
  if (quitting) { recovering = false; return; }
  const result = await dialog.showMessageBox({
    type: "error", title: "ChatTFT desktop", message: error.message,
    buttons: cleanupFailed ? ["Quit"] : ["Retry", "Quit"],
    defaultId: 0, cancelId: cleanupFailed ? 0 : 1,
  });
  recovering = false;
  if (!cleanupFailed && result.response === 0) await startApplication();
  else app.quit();
}

/** Restart owned ChatTFT services and load the page after readiness checks. */
async function restartApplication() {
  if (quitting || recovering || restarting || runtime?.state !== "running") return;
  restarting = true;
  frontendUrl = undefined;
  showStatus("Restarting ChatTFT…");
  try {
    // Fully stop the old process tree before constructing a fresh interpreter.
    // This also rebuilds production assets and renews the dev proxy when needed.
    await runtime.stop();
    if (!quitting) await startApplication();
  } catch (error) {
    await handleFailure(error);
  } finally {
    restarting = false;
  }
}

/**
 * Reload the active workspace; force reload restarts ChatTFT's owned services.
 * Args:
 *   ignoreCache: Whether the native Force Reload command was selected.
 */
function reloadView(ignoreCache) {
  if (!window || !workspace || quitting || recovering || restarting) return;
  if (["chat", "rolldown", "flowchart", "compositions"].includes(workspace.active) && ignoreCache) return restartApplication();
  if (!["chat", "rolldown", "flowchart", "compositions"].includes(workspace.active) && workspace.state !== "ready") workspace.loadExternal(workspace.active);
  else if (ignoreCache) workspace.currentContents().reloadIgnoringCache();
  else workspace.currentContents().reload();
}

/** Adjust only the selected application's zoom, keeping navigation at fixed size. */
function zoomView(delta) {
  if (!window || !workspace) return;
  const contents = workspace.currentContents();
  contents.setZoomLevel(delta === 0 ? 0 : contents.getZoomLevel() + delta);
}

/** Install platform editing/navigation controls without changing React content. */
function installMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform === "darwin" ? [{ role: "appMenu" }] : []),
    { label: "File", submenu: [{ role: process.platform === "darwin" ? "close" : "quit" }] },
    { role: "editMenu" },
    { label: "View", submenu: [
      // Product tabs (Ctrl/Cmd+1-6) come first, in tab-bar order; the two
      // external integrations (Langfuse, Database) follow at +7/+8. Selecting
      // "compositions" while workspace.compositionsEnabled is false is a
      // no-op (see DesktopWorkspace#select), the same guard that already
      // protects the hidden nav button and the IPC command bridge.
      { label: "ChatTFT", accelerator: "CmdOrCtrl+1", click: () => workspace?.select("chat") },
      { label: "Compositions", accelerator: "CmdOrCtrl+2", click: () => workspace?.select("compositions") },
      { label: "Rolldown", accelerator: "CmdOrCtrl+3", click: () => workspace?.select("rolldown") },
      { label: "Flowchart", accelerator: "CmdOrCtrl+4", click: () => workspace?.select("flowchart") },
      { label: "VOD Review", accelerator: "CmdOrCtrl+5", click: () => workspace?.select("vod") },
      { label: "Wisps", accelerator: "CmdOrCtrl+6", click: () => workspace?.select("wisps") },
      { label: "Langfuse", accelerator: "CmdOrCtrl+7", click: () => workspace?.select("langfuse") },
      { label: "Database", accelerator: "CmdOrCtrl+8", click: () => workspace?.select("database") },
      { type: "separator" },
      { label: "Reload", accelerator: "CmdOrCtrl+R", click: () => reloadView(false) },
      { label: "Force Reload", accelerator: "CmdOrCtrl+Shift+R", click: () => reloadView(true) },
      { label: "Developer Tools", accelerator: "CmdOrCtrl+Shift+I", click: () => workspace?.currentContents().toggleDevTools() },
      { type: "separator" }, { label: "Actual Size", accelerator: "CmdOrCtrl+0", click: () => zoomView(0) },
      { label: "Zoom In", accelerator: "CmdOrCtrl+Plus", click: () => zoomView(0.5) },
      { label: "Zoom Out", accelerator: "CmdOrCtrl+-", click: () => zoomView(-0.5) },
      { type: "separator" }, { role: "togglefullscreen" },
    ] },
    { role: "windowMenu" },
  ]));
}

if (!app.requestSingleInstanceLock()) {
  console.log("Focusing the existing ChatTFT desktop window for this checkout.");
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!app.isReady() || quitting) return;
    if (!window) createWindow();
    if (window.isMinimized()) window.restore();
    window.focus();
  });
  app.on("activate", () => { if (!window && !quitting) createWindow(); });
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
  app.on("before-quit", (event) => {
    if (quitAllowed) return;
    event.preventDefault();
    if (quitting) return;
    quitting = true;
    runtime?.removeAllListeners("failure");
    Promise.allSettled([runtime?.stop(), ...Array.from(videoRuntimes.values(), (service) => service.stop()), ...videoStarts.values()]).then((results) => {
      for (const result of results) {
        if (result.status === "rejected") console.error(result.reason.message);
      }
    }).finally(() => {
      quitAllowed = true;
      app.quit();
    });
  });
  // Windows GUI executables do not reliably inherit fd 0. The bootstrap owns
  // a named pipe instead; its disconnection has the same lifetime semantics.
  const parentPipe = process.env.CHATTFT_DESKTOP_PARENT_PIPE;
  delete process.env.CHATTFT_DESKTOP_PARENT_PIPE;
  const parentInput = parentPipe ? net.createConnection(parentPipe) : process.stdin;
  parentInput.on("error", () => app.quit());
  const parent = createInterface({ input: parentInput });
  parent.on("line", (line) => { if (line.trim() === "shutdown") app.quit(); });
  parent.on("close", () => { console.log("Desktop launch pipe closed; stopping services."); app.quit(); });
  app.whenReady().then(async () => {
    if (quitting) return;
    if (!node) {
      dialog.showErrorBox("Missing Node launcher", "Launch with npm start or npm run dev from desktop/.");
      app.quit();
      return;
    }
    session.defaultSession.setPermissionRequestHandler((_contents, permission, callback, details) => {
      callback(permissionAllowed(permission, details.requestingUrl, frontendUrl, details.isMainFrame));
    });
    session.defaultSession.setPermissionCheckHandler((_contents, permission, origin, details) => (
      permissionAllowed(permission, details.requestingUrl || origin, frontendUrl, details.isMainFrame)
    ));
    installMenu();
    createWindow();
    for (const tab of ["vod", "wisps"]) {
      ensureVideoWorkspace(tab).then(() => {
        if (!quitting && workspace?.active === tab) workspace.loadExternal(tab);
      }).catch((error) => {
        console.error(`${tab} startup: ${error.message}`);
        workspace?.fail(tab);
      });
    }
    await startApplication();
  }).catch(handleFailure);
}
