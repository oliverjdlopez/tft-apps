/** Opt-in native Electron regression using local HTML fixtures, without services. */
import { app, BrowserWindow, session } from "electron";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { DesktopWorkspace } from "../workspace.mjs";

const profile = mkdtempSync(path.join(os.tmpdir(), "chattft-workspace-test-"));
app.setPath("userData", profile);
app.setPath("sessionData", profile);
app.on("window-all-closed", () => {});

/** Wait for real renderer events with a bounded test deadline. */
async function until(predicate) {
  const deadline = Date.now() + 10000;
  while (!await predicate()) {
    if (Date.now() > deadline) throw new Error("Workspace assertion timed out");
    await delay(50);
  }
}

/** Verify shell IPC, retained page state, connection recovery, and owned cleanup. */
async function run() {
  await app.whenReady();
  let available = true;
  const partition = session.fromPartition("persist:langfuse");
  partition.protocol.handle("http", () => {
    if (!available) throw new Error("Fixture offline");
    return new Response("<h1>Langfuse fixture</h1><input id='state'>", { headers: { "content-type": "text/html" } });
  });
  const databasePartition = session.fromPartition("persist:cloudbeaver");
  databasePartition.protocol.handle("http", () => new Response("<h1>Database fixture</h1><textarea id='sql'></textarea>", { headers: { "content-type": "text/html" } }));
  const window = new BrowserWindow({ show: false, width: 1000, height: 700, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false,
    preload: fileURLToPath(new URL("../workspace-preload.cjs", import.meta.url)),
  } });
  const workspace = new DesktopWorkspace(window, () => {});
  try {
    await until(() => window.webContents.executeJavaScript("Boolean(document.getElementById('langfuse') && window.desktopWorkspace)").catch(() => false));
    await workspace.chat.webContents.loadURL("data:text/html,<input id='chat'>");
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('compositions').hidden"), true);
    workspace.select("compositions");
    assert.equal(workspace.active, "chat");
    workspace.compositionsEnabled = true;
    workspace.layout();
    await workspace.compositions.webContents.loadURL("data:text/html,<input id='experiment'>");
    await workspace.compositions.webContents.executeJavaScript("document.getElementById('experiment').value = 'saved selection'");
    await until(() => window.webContents.executeJavaScript("!document.getElementById('compositions').hidden"));
    await window.webContents.executeJavaScript("document.getElementById('compositions').click()");
    await until(() => workspace.active === "compositions");
    assert.equal(await workspace.compositions.webContents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
    workspace.select("chat");
    workspace.select("compositions");
    assert.equal(await workspace.compositions.webContents.executeJavaScript("document.getElementById('experiment').value"), "saved selection");
    workspace.select("chat");

    await workspace.chat.webContents.executeJavaScript("document.getElementById('chat').value = 'keep chat'");
    await window.webContents.executeJavaScript("document.getElementById('langfuse').click()");
    await until(() => workspace.state === "ready");
    assert.equal(workspace.active, "langfuse");
    assert.equal(await workspace.pages.get("langfuse").view.webContents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
    await workspace.pages.get("langfuse").view.webContents.executeJavaScript("document.getElementById('state').value = 'keep langfuse'");
    workspace.select("chat");
    assert.equal(await workspace.chat.webContents.executeJavaScript("document.getElementById('chat').value"), "keep chat");
    workspace.select("langfuse");
    assert.equal(await workspace.pages.get("langfuse").view.webContents.executeJavaScript("document.getElementById('state').value"), "keep langfuse");
    await window.webContents.executeJavaScript("document.getElementById('database').click()");
    await until(() => workspace.active === "database" && workspace.state === "ready");
    const databaseContents = workspace.pages.get("database").view.webContents;
    assert.equal(await databaseContents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
    await databaseContents.executeJavaScript("document.getElementById('sql').value = 'SELECT 1'");
    workspace.select("chat");
    workspace.select("database");
    assert.equal(await databaseContents.executeJavaScript("document.getElementById('sql').value"), "SELECT 1");
    workspace.select("langfuse");
    available = false;
    workspace.pages.get("langfuse").view.webContents.reload();
    await until(() => workspace.state === "error");
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('recovery').hidden"), false);
    available = true;
    await window.webContents.executeJavaScript("document.getElementById('retry').click()");
    await until(() => workspace.state === "ready");
    const compositionContents = workspace.compositions.webContents;
    const chatContents = workspace.chat.webContents;
    const langfuseContents = workspace.pages.get("langfuse").view.webContents;
    window.destroy();
    await until(() => chatContents.isDestroyed() && compositionContents.isDestroyed() && langfuseContents.isDestroyed() && databaseContents.isDestroyed());
    assert.equal(chatContents.isDestroyed(), true);
    assert.equal(langfuseContents.isDestroyed(), true);
    console.log("PASS: native shell IPC, retained tabs, isolated renderer, offline/retry, and cleanup");
  } finally {
    if (!window.isDestroyed()) window.destroy();
    partition.protocol.unhandle("http");
    databasePartition.protocol.unhandle("http");
  }
  // Optional live check reads the first-run UI without configuring the user's
  // account or importing any of their database credentials.
  if (process.env.CHATTFT_TEST_CLOUDBEAVER === "1") {
    const liveWindow = new BrowserWindow({ show: true, width: 1200, height: 800, webPreferences: {
      sandbox: true, contextIsolation: true, nodeIntegration: false,
      preload: fileURLToPath(new URL("../workspace-preload.cjs", import.meta.url)),
    } });
    const liveWorkspace = new DesktopWorkspace(liveWindow, () => {});
    try {
      liveWorkspace.select("database");
      await until(() => liveWorkspace.state === "ready");
      const contents = liveWorkspace.currentContents();
      await until(() => contents.executeJavaScript("document.body.innerText.includes('CloudBeaver') && !document.body.innerText.includes('Installing...')"));
      assert.equal(await contents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
      liveWorkspace.select("chat");
      liveWorkspace.select("database");
      assert.equal(liveWorkspace.currentContents(), contents);
      if (process.env.CHATTFT_TEST_SCREENSHOT) {
        writeFileSync(process.env.CHATTFT_TEST_SCREENSHOT, (await contents.capturePage()).toPNG());
      }
      console.log("PASS: Windows Electron loads live CloudBeaver through localhost and retains its view");
    } finally { liveWindow.destroy(); }
  }

}
run().then(() => app.exit(0), (error) => { console.error(error); app.exit(1); });
app.on("quit", () => {
  // Chromium may still hold profile files on Windows; the unique test profile
  // is disposable and must never fall back to deleting the normal app profile.
  try { rmSync(profile, { recursive: true, force: true }); } catch { /* OS releases handles at process exit. */ }
});
