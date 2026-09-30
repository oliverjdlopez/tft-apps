/** Verify native reload commands use the owned runtime lifecycle. */
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { registerHooks } from "node:module";
import { mkdtempSync, rmSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

/** Capture page navigation without a native renderer. */
class Contents extends EventEmitter {
  /** Initialize reload counters. */
  constructor() { super(); this.reloads = 0; this.forced = 0; this.urls = []; }
  /** Record page readiness navigation. */
  async loadURL(url) { this.urls.push(url); }
  /** Accept launcher status pages. */
  async loadFile() {}
  /** Accept popup restrictions. */
  setWindowOpenHandler() {}
  /** Record ordinary reload. */
  reload() { this.reloads++; }
  /** Record cache-bypassing reload. */
  reloadIgnoringCache() { this.forced++; }
}

/** Simulate an owned service generation with controllable stop failures. */
class Runtime extends EventEmitter {
  static instances = [];
  /** Record each fresh interpreter generation. */
  constructor() { super(); this.state = "idle"; this.stopCalls = 0; Runtime.instances.push(this); }
  /** Simulate readiness of a new process generation. */
  async start() {
    if (Runtime.nextStartError) {
      const error = Runtime.nextStartError;
      Runtime.nextStartError = undefined;
      throw error;
    }
    this.state = "running";
    return "http://127.0.0.1:8300";
  }
  /** Allow tests to pause shutdown before a new runtime may start. */
  async stop() {
    this.stopCalls++;
    this.state = "stopping";
    await this.stopGate;
    if (this.stopError) throw this.stopError;
    this.state = "stopped";
  }
}

/** Provide independent hosted pages to the native menu. */
class Workspace {
  /** Create separate page counters and expose the active fixture. */
  constructor() {
    Workspace.current = this;
    this.active = "chat";
    this.state = "ready";
    this.chat = { webContents: new Contents() };
    this.rolldown = { webContents: new Contents() };
    this.flowchart = { webContents: new Contents() };
    this.compositions = { webContents: new Contents() };
    this.external = new Contents();
  }
  /** Accept layout updates following configuration changes. */
  layout() {}
  /** Return the selected renderer. */
  currentContents() { return this.active === "chat" ? this.chat.webContents : this.active === "rolldown" ? this.rolldown.webContents : this.active === "flowchart" ? this.flowchart.webContents : this.active === "compositions" ? this.compositions.webContents : this.external; }
  /** Select an existing workspace. */
  select(name) { this.active = name; }
  /** Record retry of an unavailable external page. */
  loadExternal() { this.retried = true; }
}

/** Supply the window events used by the application lifecycle. */
class Window extends EventEmitter {
  /** Track whether the window is available for status messages. */
  isDestroyed() { return false; }
}

test("Force Reload restarts ChatTFT once, preserves external tabs, and handles failed cleanup", async (t) => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ json: async () => ({ composition_workbench: true }) });
  t.after(() => { globalThis.fetch = originalFetch; });
  const profile = mkdtempSync(path.join(os.tmpdir(), "chattft reload "));
  t.after(() => rmSync(profile, { recursive: true, force: true }));
  const app = new EventEmitter();
  let menu;
  let quitCalls = 0;
  const dialogs = [];
  Object.assign(app, {
    setName() {}, getPath: () => profile, setPath() {},
    requestSingleInstanceLock: () => true,
    whenReady: async () => {},
    quit: () => { quitCalls++; },
  });
  globalThis.reloadFixture = {
    app, BrowserWindow: Window, Runtime, Workspace,
    VideoRuntime: class extends EventEmitter {
      async start() { this.state = "running"; }
      async stop() { this.state = "stopped"; }
    },
    createInterface: () => new EventEmitter(),
    dialog: { showMessageBox: async (options) => { dialogs.push(options); return { response: 0 }; } },
    Menu: { buildFromTemplate: (items) => items, setApplicationMenu: (items) => { menu = items; } },
    session: { defaultSession: { setPermissionRequestHandler() {}, setPermissionCheckHandler() {} } },
    shell: {},
  };
  const hooks = registerHooks({
    resolve(specifier, context, next) {
      const exports = specifier === "node:readline" && context.parentURL?.endsWith("/main.mjs")
        ? "createInterface"
        : specifier === "electron"
        ? "app,BrowserWindow,dialog,Menu,session,shell"
        : specifier === "./video-runtime.mjs" ? "VideoRuntime"
        : specifier === "./runtime.mjs" ? "Runtime:DesktopRuntime"
        : specifier === "./workspace.mjs" ? "Workspace:DesktopWorkspace" : null;
      if (!exports) return next(specifier, context);
      return { url: `data:text/javascript,export const {${exports}}=globalThis.reloadFixture`, shortCircuit: true };
    },
  });
  const previousNode = process.env.CHATTFT_DESKTOP_NODE;
  process.env.CHATTFT_DESKTOP_NODE = process.execPath;
  t.after(() => {
    hooks.deregister();
    if (previousNode === undefined) delete process.env.CHATTFT_DESKTOP_NODE;
    else process.env.CHATTFT_DESKTOP_NODE = previousNode;
  });
  await import("../main.mjs");
  await new Promise((resolve) => setImmediate(resolve));
  const commands = menu.find((item) => item.label === "View").submenu;
  const reload = commands.find((item) => item.label === "Reload").click;
  const force = commands.find((item) => item.label === "Force Reload").click;
  const workspace = Workspace.current;
  const initial = Runtime.instances[0];

  reload();
  assert.equal(workspace.chat.webContents.reloads, 1);
  assert.equal(initial.stopCalls, 0);
  for (const page of ["langfuse", "database"]) {
    workspace.select(page);
    force();
  }
  assert.equal(workspace.external.forced, 2);
  assert.equal(initial.stopCalls, 0);

  workspace.select("chat");
  let finishStop;
  initial.stopGate = new Promise((resolve) => { finishStop = resolve; });
  const restarting = force();
  force();
  reload();
  assert.equal(initial.stopCalls, 1);
  assert.equal(Runtime.instances.length, 1);
  assert.equal(workspace.chat.webContents.reloads, 1);
  finishStop();
  await restarting;
  assert.equal(initial.state, "stopped");
  assert.equal(Runtime.instances.length, 2);
  assert.equal(Runtime.instances[1].state, "running");
  assert.equal(workspace.chat.webContents.urls.length, 2);

  assert.equal(workspace.rolldown.webContents.urls.at(-1), "http://127.0.0.1:8300/rolldown");
  assert.equal(workspace.flowchart.webContents.urls.at(-1), "http://127.0.0.1:8300/flowchart");
  assert.equal(workspace.compositions.webContents.urls.at(-1), "http://127.0.0.1:8300/compositions");
  workspace.select("compositions");
  reload();
  assert.equal(workspace.compositions.webContents.reloads, 1);
  workspace.select("rolldown");
  Runtime.nextStartError = new Error("Backend startup failed.");
  await force();
  assert.deepEqual(dialogs[0].buttons, ["Retry", "Quit"]);
  assert.equal(Runtime.instances.length, 4);
  assert.equal(Runtime.instances[2].state, "stopped");
  assert.equal(Runtime.instances[3].state, "running");

  Runtime.instances[3].stopError = new Error("Owned child could not stop.");
  await force();
  assert.equal(Runtime.instances.length, 4);
  assert.deepEqual(dialogs[1].buttons, ["Quit"]);
  assert.equal(quitCalls, 1);
});
