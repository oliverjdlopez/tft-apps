/** Compose persistent application views beneath the desktop's own navigation. */
import { WebContentsView, ipcMain, session } from "electron";
import { fileURLToPath, pathToFileURL } from "node:url";
import { navigationPolicy, permissionAllowed, workspaceCommandAllowed } from "./utils.mjs";

const shellPath = fileURLToPath(new URL("./workspace.html", import.meta.url));
const externalPages = {
  vod: { url: "http://localhost:5174", partition: "persist:vod-review" },
  wisps: { url: "http://localhost:5174/wisp_classifier", partition: "persist:wisps" },
  langfuse: { url: "http://localhost:15510/project/tft-apps-evals", partition: "persist:langfuse" },
  database: { url: "http://localhost:8979", partition: "persist:cloudbeaver" },
};
const preferences = { nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true };

/** Own desktop navigation, isolated external pages, and child-view cleanup. */
export class DesktopWorkspace {
  /**
   * Attach persistent views to a window whose renderer contains only local chrome.
   * Args:
   *   window: Owning BrowserWindow; openExternal: validated browser-link handler.
   */
  constructor(window, openExternal, ensureVideo = async () => {}) {
    this.ensureVideo = ensureVideo;
    this.window = window;
    this.active = "chat";
    this.compositionsEnabled = false;
    this.pages = new Map();
    this.closed = false;
    this.chat = new WebContentsView({ webPreferences: preferences });
    this.rolldown = new WebContentsView({ webPreferences: preferences });
    this.flowchart = new WebContentsView({ webPreferences: preferences });
    this.compositions = new WebContentsView({ webPreferences: preferences });
    window.contentView.addChildView(this.compositions);
    window.contentView.addChildView(this.chat);
    window.contentView.addChildView(this.rolldown);
    window.contentView.addChildView(this.flowchart);
    for (const [tab, definition] of Object.entries(externalPages)) {
      this.attachExternal(tab, definition, openExternal);
    }
    // Only the local top-level shell receives this bridge. No hosted page
    // can invoke desktop actions, even if it learns the IPC channel name.
    this.command = (event, action) => {
      if (!workspaceCommandAllowed(event, window.webContents, pathToFileURL(shellPath).href, action)) return;
      if (action === "retry") this.loadExternal(this.active);
      else this.select(action);
    };
    ipcMain.on("desktop-workspace", this.command);
    window.webContents.on("will-navigate", (event) => event.preventDefault());
    window.webContents.on("will-redirect", (event) => event.preventDefault());
    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    window.webContents.on("will-attach-webview", (event) => event.preventDefault());
    window.webContents.on("did-finish-load", () => this.layout());
    window.on("resize", () => this.layout());
    window.on("closed", () => this.close());
    window.loadFile(shellPath).catch(() => console.error("Could not load desktop navigation."));
    this.layout();
  }

  /**
   * Attach an isolated external application with independent recovery state.
   * Args:
   *   tab: Fixed workspace identifier; definition: trusted URL and session;
   *   openExternal: Validated system-browser link handler.
   */
  attachExternal(tab, definition, openExternal) {
    const view = new WebContentsView({ webPreferences: { ...preferences, partition: definition.partition } });
    const page = { ...definition, view, state: "idle", generation: 0 };
    this.pages.set(tab, page);
    this.window.contentView.addChildView(view);
    const contents = view.webContents;
    const origin = new URL(page.url).origin;
    const partition = session.fromPartition(page.partition);
    partition.setPermissionRequestHandler((_contents, permission, callback, details) => {
      callback(permissionAllowed(permission, details.requestingUrl, origin, details.isMainFrame));
    });
    partition.setPermissionCheckHandler((_contents, permission, requestingOrigin, details) => (
      permissionAllowed(permission, details.requestingUrl || requestingOrigin, origin, details.isMainFrame)
    ));
    contents.on("will-navigate", (event) => {
      const policy = navigationPolicy(event.url, origin);
      if (policy !== "internal") {
        event.preventDefault();
        if (policy === "external") openExternal(event.url);
      }
    });
    contents.on("will-redirect", (event) => {
      if (navigationPolicy(event.url, origin) !== "internal") event.preventDefault();
    });
    contents.setWindowOpenHandler(({ url }) => {
      const policy = navigationPolicy(url, origin);
      if (policy === "internal") contents.loadURL(url).catch(() => this.fail(tab));
      else if (policy === "external") openExternal(url);
      return { action: "deny" };
    });
    contents.on("will-attach-webview", (event) => event.preventDefault());
    contents.on("did-fail-load", (_event, code, _description, _url, mainFrame) => {
      if (mainFrame && code !== -3) this.fail(tab);
    });
    contents.on("render-process-gone", () => this.fail(tab));
    contents.on("did-finish-load", () => {
      if (page.state !== "loading" || navigationPolicy(contents.getURL(), origin) !== "internal") return;
      clearTimeout(page.timer);
      page.state = "ready";
      this.layout();
    });
  }

  /** Return the selected page's loading state for native menu actions. */
  get state() { return this.pages.get(this.active)?.state ?? "ready"; }

  /**
   * Switch visibility without navigating or recreating any application.
   * Args:
   *   tab: ChatTFT, Rolldown, Flowchart, Langfuse, or Database view identifier.
   */
  select(tab) {
    if (tab === "compositions" && !this.compositionsEnabled) return;
    if ((!["chat", "rolldown", "flowchart", "compositions"].includes(tab) && !this.pages.has(tab)) || this.closed) return;
    this.active = tab;
    if (this.state === "idle") this.loadExternal(tab);
    this.layout();
    if (this.state === "ready") this.currentContents().focus();
  }

  /** Return the active page for native editing, zoom, reload, and devtools. */
  currentContents() {
    if (this.active === "compositions") return this.compositions.webContents;
    if (this.active === "chat") return this.chat.webContents;
    if (this.active === "rolldown") return this.rolldown.webContents;
    if (this.active === "flowchart") return this.flowchart.webContents;
    return this.pages.get(this.active).view.webContents;
  }

  /**
   * Load or retry an external page independently of other tabs and backend startup.
   * Args:
   *   tab: Fixed external workspace identifier.
   */
  loadExternal(tab) {
    const page = this.pages.get(tab);
    if (!page || this.closed || page.state === "loading") return;
    page.state = "loading";
    const generation = ++page.generation;
    this.layout();
    // Video startup has its own deadline. Begin the page deadline only after
    // service readiness so model imports do not exhaust the browser timeout.
    const ready = ["vod", "wisps"].includes(tab) ? this.ensureVideo(tab) : Promise.resolve();
    const navigate = () => {
      if (this.closed || generation !== page.generation || page.state !== "loading") return;
      page.timer = setTimeout(() => this.fail(tab), 15000);
      return page.view.webContents.loadURL(page.url);
    };
    // Keep the existing immediate navigation for independently managed tools.
    const navigation = ["vod", "wisps"].includes(tab) ? ready.then(navigate) : navigate();
    Promise.resolve(navigation).catch((error) => {
      // An old navigation promise can settle after the user has already retried.
      if (generation === page.generation && error.code !== "ERR_ABORTED") this.fail(tab);
    });
  }

  /**
   * Show recoverable failure for one external page without stopping other views.
   * Args:
   *   tab: Identifier of the failing external application.
   */
  fail(tab) {
    const page = this.pages.get(tab);
    if (this.closed || !page) return;
    clearTimeout(page.timer);
    page.state = "error";
    page.view.webContents.stop();
    this.layout();
  }

  /** Size child pages below navigation and publish only the active UI state. */
  layout() {
    if (this.closed) return;
    const [width, height] = this.window.getContentSize();
    const bounds = { x: 0, y: 48, width, height: Math.max(0, height - 48) };
    this.compositions.setBounds(bounds);
    this.compositions.setVisible(this.active === "compositions" && this.compositionsEnabled);
    this.chat.setBounds(bounds);
    this.chat.setVisible(this.active === "chat");
    this.rolldown.setBounds(bounds);
    this.rolldown.setVisible(this.active === "rolldown");
    this.flowchart.setBounds(bounds);
    this.flowchart.setVisible(this.active === "flowchart");
    for (const [tab, page] of this.pages) {
      page.view.setBounds(bounds);
      page.view.setVisible(this.active === tab && page.state === "ready");
    }
    this.window.webContents.send("desktop-workspace-state", { active: this.active, state: this.state, compositionsEnabled: this.compositionsEnabled });
  }

  /** Destroy every child renderer and deadline when the owning window closes. */
  close() {
    this.closed = true;
    ipcMain.removeListener("desktop-workspace", this.command);
    for (const page of this.pages.values()) clearTimeout(page.timer);
    for (const view of [this.chat, this.rolldown, this.flowchart, this.compositions, ...Array.from(this.pages.values(), (page) => page.view)]) {
      if (!view.webContents.isDestroyed()) view.webContents.close();
    }
  }
}
