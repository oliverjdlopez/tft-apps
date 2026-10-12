/** Opt-in check against local Langfuse using a disposable Electron profile. */
import { app, BrowserWindow, session, clipboard, Menu } from "electron";
import assert from "node:assert/strict";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { DesktopWorkspace } from "../workspace.mjs";
import { langfuseRunId, langfuseRunMenuItems, readLangfuseSettings, signInLangfuse } from "../langfuse.mjs";

const root = process.env.CHATTFT_LANGFUSE_TEST_ROOT || fileURLToPath(new URL("../../", import.meta.url));
const wsl = process.env.CHATTFT_LANGFUSE_TEST_DISTRO ? { distro: process.env.CHATTFT_LANGFUSE_TEST_DISTRO } : undefined;
const settings = readLangfuseSettings(root, { wsl });
// The caller owns cleanup after Electron exits, when Windows releases its files.
const profile = process.env.CHATTFT_LANGFUSE_TEST_PROFILE;
if (!profile) throw new Error("Set CHATTFT_LANGFUSE_TEST_PROFILE to a disposable profile directory and remove it after testing.");
app.setPath("userData", profile);
app.setPath("sessionData", profile);
app.on("window-all-closed", () => {});

async function until(predicate) {
  const deadline = Date.now() + 30000;
  while (!await predicate()) {
    if (Date.now() > deadline) throw new Error("Langfuse view did not become ready.");
    await delay(100);
  }
}

let stage = "settings";

async function run() {
  assert.ok(settings.email && settings.password, "Local Langfuse sign-in settings are required.");
  stage = "app-ready";
  await app.whenReady();
  const partition = session.fromPartition("persist:langfuse");
  stage = "session-probe";
  const before = await (await partition.fetch(new URL("/api/auth/session", settings.url).href)).json();
  let submissions = 0;
  partition.webRequest.onBeforeRequest({ urls: [new URL("/api/auth/callback/credentials", settings.url).href] }, (_details, callback) => {
    submissions++;
    callback({});
  });
  const window = new BrowserWindow({ show: false, width: 1200, height: 800, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false,
    preload: fileURLToPath(new URL("../workspace-preload.cjs", import.meta.url)),
  } });
  stage = "workspace";
  const workspace = new DesktopWorkspace(window, () => {}, undefined, undefined, {
    langfuseUrl: settings.url,
    onLangfuseRunsChanged(runs) {
      Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: "View", submenu: [
        { id: "copy-run", label: "Copy Langfuse run ID", submenu: langfuseRunMenuItems(runs,
          id => workspace.copyLangfuseRunId(id)) },
      ] }]));
    },
    prepareLangfuse: async received => {
      stage = "automatic-login";
      assert.equal(received, partition);
      assert.equal(await signInLangfuse(received, settings), true, "Automatic sign-in failed.");
    },
  });
  try {
    workspace.select("langfuse");
    const contents = workspace.currentContents();
    stage = "view-ready";
    await until(() => workspace.state === "ready");
    await until(() => contents.getURL().startsWith(settings.url));
    stage = "renderer-session";
    const verified = await contents.executeJavaScript("fetch('/api/auth/session').then(r => r.json()).then(s => Boolean(s.user))");
    assert.equal(verified, true, "The hosted page did not inherit the authenticated session.");
    stage = "project-render";
    await until(() => contents.executeJavaScript("Boolean(document.querySelector('a[href*=\"/datasets\"]'))"));
    assert.equal(await contents.executeJavaScript("Boolean(document.querySelector('input[type=password]'))"), false);
    assert.equal(await contents.executeJavaScript("typeof window.desktopWorkspace"), "undefined");
    assert.equal(submissions, before.user ? 0 : 1);
    if (process.env.CHATTFT_LANGFUSE_TEST_RUN_URL) {
      stage = "run-reference";
      const runUrl = process.env.CHATTFT_LANGFUSE_TEST_RUN_URL;
      const runId = langfuseRunId(runUrl, settings.url);
      assert.ok(runId, "The test run must belong to the configured Langfuse origin.");
      await contents.loadURL(runUrl);
      // Let the legacy run link redirect into v4's results comparison page.
      await until(() => new URL(contents.getURL()).pathname.endsWith("/experiments/results"));
      await delay(500);
      const entries = Menu.getApplicationMenu().getMenuItemById("copy-run").submenu.items;
      assert.ok(entries.some(entry => entry.label.endsWith(": " + runId)));
      const originalWrite = clipboard.writeText;
      let copied;
      clipboard.writeText = value => { copied = value; };
      try {
        for (const entry of entries) {
          entry.click();
          assert.equal(copied, entry.label.split(": ")[1]);
        }
      } finally { clipboard.writeText = originalWrite; }
      console.log("PASS: live Langfuse comparison run IDs appear in the native menu and copy correctly.");
    }
    workspace.select("chat");
    workspace.select("langfuse");
    assert.equal(workspace.currentContents(), contents);
    await partition.cookies.flushStore();
    console.log(`PASS: ${process.platform} Langfuse project rendered signed in; ${before.user ? "saved session reused" : "fresh sign-in succeeded"}; hosted page has no desktop bridge.`);
  } finally {
    workspace.close();
    window.destroy();
  }
}

run().then(() => app.quit()).catch(() => {
  // A failed assertion must never dump settings, cookies, or credential bodies.
  console.error(`FAIL: live Langfuse sign-in or authenticated project rendering did not pass at ${stage}.`);
  app.exit(1);
});
