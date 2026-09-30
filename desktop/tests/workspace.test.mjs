/** Exercise desktop navigation and lifecycle without starting services or a GUI. */
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { registerHooks } from "node:module";
import test from "node:test";
import { workspaceCommandAllowed } from "../utils.mjs";

/** Minimal renderer fixture retaining navigation and shutdown observations. */
class Contents extends EventEmitter {
  /** Initialize a renderer with no loaded URL or parent privileges. */
  constructor() { super(); this.mainFrame = { url: "" }; this.loads = []; }
  /** Record navigation without automatically completing it. */
  async loadURL(url) { this.url = url; this.loads.push(url); }
  /** Return the last requested location. */
  getURL() { return this.url; }
  /** Store the popup policy for direct boundary checks. */
  setWindowOpenHandler(handler) { this.popup = handler; }
  /** Record shell state delivery. */
  send(_channel, state) { this.state = state; }
  /** Record focus transfer. */
  focus() { this.focused = true; }
  /** Record cancellation on timeout or error. */
  stop() { this.stopped = true; }
  /** Report destruction for idempotent cleanup. */
  isDestroyed() { return !!this.destroyed; }
  /** Mark the renderer released. */
  close() { this.destroyed = true; }
}
/** View fixture exposing visibility and layout separately from renderer state. */
class View {
  /** Create a renderer using the production-provided preferences. */
  constructor(options) { this.options = options; this.webContents = new Contents(); }
  /** Record native layout bounds. */
  setBounds(bounds) { this.bounds = bounds; }
  /** Record native visibility without unloading the renderer. */
  setVisible(value) { this.visible = value; }
}
const ipcMain = new EventEmitter();
const partition = { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} };
globalThis.desktopElectronFixture = { WebContentsView: View, ipcMain, session: { fromPartition: () => partition } };
const hooks = registerHooks({
  resolve(specifier, context, next) {
    if (specifier === "electron") return { url: "data:text/javascript,export const {WebContentsView,ipcMain,session}=globalThis.desktopElectronFixture", shortCircuit: true };
    return next(specifier, context);
  },
});
const { DesktopWorkspace } = await import("../workspace.mjs");
hooks.deregister();

/** Create an owning-window fixture with deterministic content dimensions. */
function windowFixture() {
  const window = new EventEmitter();
  window.webContents = new Contents();
  window.contentView = { addChildView() {} };
  window.getContentSize = () => [1000, 700];
  window.loadFile = async () => {};
  return window;
}

test("switching retains loaded pages; errors and retries remain independent of ChatTFT", () => {
  const window = windowFixture();
  const workspace = new DesktopWorkspace(window, () => {});
  try {
    assert.equal(workspace.chat.visible, true);
    workspace.select("langfuse");
    assert.equal(workspace.state, "loading");
    workspace.pages.get("langfuse").view.webContents.emit("did-finish-load");
    assert.equal(workspace.pages.get("langfuse").view.visible, true);
    workspace.select("chat");
    workspace.select("langfuse");
    assert.equal(workspace.pages.get("langfuse").view.webContents.loads.length, 1);
    assert.deepEqual(workspace.pages.get("langfuse").view.bounds, { x: 0, y: 48, width: 1000, height: 652 });
    workspace.pages.get("langfuse").view.webContents.emit("did-fail-load", {}, -102, "refused", "http://localhost:15500", true);
    assert.equal(workspace.state, "error");
    assert.equal(workspace.pages.get("langfuse").view.visible, false);
    assert.equal(workspace.chat.webContents.destroyed, undefined);
    workspace.loadExternal("langfuse");
    workspace.pages.get("langfuse").view.webContents.emit("did-finish-load");
    assert.equal(workspace.state, "ready");
    workspace.pages.get("langfuse").view.webContents.emit("render-process-gone");
    assert.equal(workspace.state, "error");
  } finally { window.emit("closed"); }
  assert.equal(workspace.chat.webContents.destroyed, true);
  assert.equal(workspace.pages.get("langfuse").view.webContents.destroyed, true);
  assert.equal(ipcMain.listenerCount("desktop-workspace"), 0);
});

test("hosted pages lack a preload and unsafe navigation cannot escape the origin", () => {
  const external = [];
  const workspace = new DesktopWorkspace(windowFixture(), (url) => external.push(url));
  try {
    assert.equal(workspace.pages.get("langfuse").view.options.webPreferences.partition, "persist:langfuse");
    assert.equal(workspace.pages.get("langfuse").view.options.webPreferences.preload, undefined);
    assert.equal(workspace.chat.options.webPreferences.preload, undefined);
    const contents = workspace.pages.get("langfuse").view.webContents;
    let prevented = false;
    contents.emit("will-navigate", { url: "file:///secrets", preventDefault() { prevented = true; } });
    assert.equal(prevented, true);
    assert.equal(external.length, 0);
    contents.popup({ url: "https://langfuse.com/docs" });
    assert.deepEqual(external, ["https://langfuse.com/docs"]);
  } finally { workspace.close(); }
});

test("only the exact shell main frame can send a fixed desktop action", () => {
  const contents = new Contents();
  contents.mainFrame.url = "file:///desktop/workspace.html";
  const event = { sender: contents, senderFrame: contents.mainFrame };
  assert.equal(workspaceCommandAllowed(event, contents, contents.mainFrame.url, "chat"), true);
  assert.equal(workspaceCommandAllowed(event, contents, contents.mainFrame.url, "execute"), false);
  assert.equal(workspaceCommandAllowed({ ...event, sender: new Contents() }, contents, contents.mainFrame.url, "chat"), false);
  assert.equal(workspaceCommandAllowed({ ...event, senderFrame: { url: contents.mainFrame.url } }, contents, contents.mainFrame.url, "chat"), false);
  assert.equal(workspaceCommandAllowed(event, contents, "http://localhost:15500", "retry"), false);
});

test("three views retain state and retries target only the selected external page", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const window = windowFixture();
  const workspace = new DesktopWorkspace(window, () => {});
  const langfuse = workspace.pages.get("langfuse");
  const database = workspace.pages.get("database");
  try {
    assert.equal(database.view.webContents.loads.length, 0);
    workspace.select("langfuse");
    langfuse.view.webContents.emit("did-finish-load");
    workspace.select("database");
    assert.equal(workspace.currentContents(), database.view.webContents);
    assert.equal(workspace.state, "loading");
    assert.equal(database.view.webContents.loads[0], "http://localhost:8978");
    database.view.webContents.emit("did-finish-load");
    workspace.select("chat");
    workspace.select("database");
    assert.equal(database.view.webContents.loads.length, 1);
    assert.equal(database.view.visible, true);
    assert.equal(langfuse.view.visible, false);
    assert.deepEqual(database.view.bounds, { x: 0, y: 48, width: 1000, height: 652 });
    database.view.webContents.emit("render-process-gone");
    assert.equal(database.state, "error");
    assert.equal(langfuse.state, "ready");
    window.webContents.mainFrame.url = new URL("../workspace.html", import.meta.url).href;
    ipcMain.emit("desktop-workspace", { sender: window.webContents, senderFrame: window.webContents.mainFrame }, "retry");
    assert.equal(database.state, "loading");
    assert.equal(langfuse.view.webContents.loads.length, 1);
    workspace.select("langfuse");
    t.mock.timers.tick(15000);
    assert.equal(database.state, "error");
    assert.equal(workspace.state, "ready");
    assert.equal(langfuse.view.visible, true);
    workspace.select("database");
    workspace.loadExternal("database");
    database.view.webContents.emit("did-finish-load");
    t.mock.timers.tick(15000);
    assert.equal(database.state, "ready");
    workspace.select("chat");
    workspace.loadExternal("chat");
    assert.equal(workspace.currentContents(), workspace.chat.webContents);
  } finally { workspace.close(); }
  assert.equal(database.view.webContents.destroyed, true);
  assert.equal(langfuse.view.webContents.destroyed, true);
  assert.equal(ipcMain.listenerCount("desktop-workspace"), 0);
});

test("CloudBeaver uses a separate sandbox and cannot navigate to privileged schemes", () => {
  const external = [];
  const workspace = new DesktopWorkspace(windowFixture(), (url) => external.push(url));
  try {
    const view = workspace.pages.get("database").view;
    assert.equal(view.options.webPreferences.partition, "persist:cloudbeaver");
    assert.equal(view.options.webPreferences.preload, undefined);
    assert.equal(view.options.webPreferences.nodeIntegration, false);
    assert.equal(view.options.webPreferences.sandbox, true);
    assert.equal(view.options.webPreferences.contextIsolation, true);
    for (const url of ["file:///secrets", "javascript:alert(1)", "http://localhost:15500", "https://example.com"]) {
      let prevented = false;
      view.webContents.emit("will-redirect", { url, preventDefault() { prevented = true; } });
      assert.equal(prevented, true);
    }
    let prevented = false;
    view.webContents.emit("will-navigate", { url: "http://localhost:8978/#editor", preventDefault() { prevented = true; } });
    assert.equal(prevented, false);
    assert.deepEqual(view.webContents.popup({ url: "file:///secrets" }), { action: "deny" });
    view.webContents.popup({ url: "https://dbeaver.com/docs" });
    assert.deepEqual(external, ["https://dbeaver.com/docs"]);
    const contents = workspace.window.webContents;
    contents.mainFrame.url = new URL("../workspace.html", import.meta.url).href;
    assert.equal(workspaceCommandAllowed({ sender: contents, senderFrame: contents.mainFrame }, contents, contents.mainFrame.url, "database"), true);
    ipcMain.emit("desktop-workspace", { sender: view.webContents, senderFrame: view.webContents.mainFrame }, "database");
    assert.equal(workspace.active, "chat");
  } finally { workspace.close(); }
});


test("Rolldown retains its own view while switching and closes with its window", () => {
  const workspace = new DesktopWorkspace(windowFixture(), () => {});
  const contents = workspace.rolldown.webContents;
  try {
    contents.result = { probability: 0.75 };
    workspace.select("rolldown");
    assert.equal(workspace.currentContents(), contents);
    assert.equal(workspace.rolldown.visible, true);
    assert.equal(workspace.chat.visible, false);
    assert.equal(workspace.rolldown.options.webPreferences.preload, undefined);
    workspace.select("chat");
    workspace.select("rolldown");
    assert.equal(workspace.currentContents().result.probability, 0.75);
    assert.equal(contents.loads.length, 0);
    const shell = workspace.window.webContents;
    shell.mainFrame.url = "file:///desktop/workspace.html";
    assert.equal(workspaceCommandAllowed({ sender: shell, senderFrame: shell.mainFrame }, shell,
      shell.mainFrame.url, "rolldown"), true);
  } finally { workspace.close(); }
  assert.equal(contents.isDestroyed(), true);
});

test("Flowchart retains its own local view and is reachable from the shell bridge", () => {
  const workspace = new DesktopWorkspace(windowFixture(), () => {});
  const contents = workspace.flowchart.webContents;
  try {
    workspace.select("flowchart");
    assert.equal(workspace.currentContents(), contents);
    assert.equal(workspace.flowchart.visible, true);
    assert.equal(workspace.rolldown.visible, false);
    assert.equal(workspace.flowchart.options.webPreferences.preload, undefined);
    workspace.select("chat");
    assert.equal(workspace.flowchart.visible, false);
    assert.equal(contents.loads.length, 0);
    const shell = workspace.window.webContents;
    shell.mainFrame.url = new URL("../workspace.html", import.meta.url).href;
    assert.equal(workspaceCommandAllowed({ sender: shell, senderFrame: shell.mainFrame }, shell,
      shell.mainFrame.url, "flowchart"), true);
    ipcMain.emit("desktop-workspace", { sender: shell, senderFrame: shell.mainFrame }, "flowchart");
    assert.equal(workspace.active, "flowchart");
  } finally { workspace.close(); }
  assert.equal(contents.isDestroyed(), true);
});

test("VOD Review and Wisps load separate checkouts and retain independent recovery state", async () => {
  const workspace = new DesktopWorkspace(windowFixture(), () => {});
  try {
    for (const [tab, url] of [["vod", "http://localhost:5174"], ["wisps", "http://localhost:5175/wisp_classifier"]]) {
      workspace.select(tab);
      await Promise.resolve();
      const page = workspace.pages.get(tab);
      assert.deepEqual(page.view.webContents.loads, [url]);
      assert.equal(page.view.options.webPreferences.preload, undefined);
      page.view.webContents.emit("did-finish-load");
      assert.equal(workspace.state, "ready");
    }
    assert.notEqual(workspace.pages.get("vod").partition, workspace.pages.get("wisps").partition);
    workspace.fail("vod");
    assert.equal(workspace.pages.get("wisps").state, "ready");
    workspace.select("vod");
    workspace.loadExternal("vod");
    await Promise.resolve();
    assert.equal(workspace.pages.get("vod").view.webContents.loads.length, 2);
    workspace.select("wisps");
    assert.equal(workspace.pages.get("wisps").view.webContents.loads.length, 1);
  } finally { workspace.close(); }
});


test("Compositions waits for enabled configuration and retains its renderer across tab switches", () => {
  const window = windowFixture();
  const workspace = new DesktopWorkspace(window, () => {});
  try {
    workspace.select("compositions");
    assert.equal(workspace.active, "chat");
    assert.equal(workspace.compositions.visible, false);
    workspace.compositionsEnabled = true;
    workspace.select("compositions");
    const contents = workspace.currentContents();
    contents.editorState = "retained experiment selection";
    workspace.select("chat");
    workspace.select("compositions");
    assert.equal(workspace.currentContents(), contents);
    assert.equal(contents.editorState, "retained experiment selection");
    assert.equal(workspace.compositions.options.webPreferences.preload, undefined);
    assert.equal(workspace.compositions.options.webPreferences.sandbox, true);
  } finally { workspace.close(); }
  assert.equal(workspace.compositions.webContents.isDestroyed(), true);
});
