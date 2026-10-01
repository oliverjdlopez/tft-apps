/** Expose only fixed workspace actions to the local desktop shell. */
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("desktopWorkspace", {
  /** Send an allowlisted tab selection or retry request. */
  select(action) {
    if (["chat", "rolldown", "flowchart", "compositions", "vod", "langfuse", "database", "media", "retry"].includes(action)) ipcRenderer.send("desktop-workspace", action);
  },
  /** Invoke fixed media operations without exposing arbitrary URLs or paths. */
  media(action, value) {
    if (!["list", "read", "copy"].includes(action)) return Promise.resolve({ error: "Unknown media action." });
    return ipcRenderer.invoke("desktop-media", action, value);
  },
  /** Deliver sanitized workspace state without exposing Electron event objects. */
  onState(callback) {
    ipcRenderer.on("desktop-workspace-state", (_event, state) => callback(state));
  },
});
