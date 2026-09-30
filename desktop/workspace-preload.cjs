/** Expose only fixed workspace actions to the local desktop shell. */
const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("desktopWorkspace", {
  /** Send an allowlisted tab selection or retry request. */
  select(action) {
    if (["chat", "rolldown", "flowchart", "compositions", "vod", "wisps", "langfuse", "database", "retry"].includes(action)) ipcRenderer.send("desktop-workspace", action);
  },
  /** Deliver sanitized workspace state without exposing Electron event objects. */
  onState(callback) {
    ipcRenderer.on("desktop-workspace-state", (_event, state) => callback(state));
  },
});
