/** Opt-in native Electron regression using local HTML fixtures, without services. */
import { app, BrowserWindow, session, clipboard } from "electron";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { createServer } from "node:http";
import { once } from "node:events";
import { DesktopWorkspace } from "../workspace.mjs";
import { createMediaReader } from "../media.mjs";

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
  const first = { reference: `tft-resource:${"a".repeat(32)}`, kind: "text", name: "<img src=x onerror=alert(1)> transcript.txt", source: "youtube:fixture", size: 30 };
  const second = { reference: `tft-resource:${"b".repeat(32)}`, kind: "data", name: "segments.json", source: "vod:fixture", size: 30 };
  const otherMedia = [
    { kind: "image", name: "board.png", content_type: "image/png" },
    { kind: "audio", name: "recording.wav", content_type: "audio/wav" },
    { kind: "video", name: "clip.mp4", content_type: "video/mp4" },
    { kind: "data", name: "artifact.bin", content_type: "application/octet-stream" },
  ].map((resource, index) => ({ ...resource, reference: `tft-resource:${String(index + 1).repeat(32)}`, source: "media:fixture", size: 100 }));
  const allMedia = [first, second, ...otherMedia];
  // Observe the actual shell IPC action without replacing the user's clipboard.
  const writeClipboard = clipboard.writeText;
  let copiedReference;
  clipboard.writeText = (value) => { copiedReference = value; };
  const png = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==", "base64");
  const wav = Buffer.alloc(44 + 1600);
  wav.write("RIFF"); wav.writeUInt32LE(wav.length - 8, 4); wav.write("WAVEfmt ", 8);
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24); wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34); wav.write("data", 36); wav.writeUInt32LE(1600, 40);
  let transcriptMissing = false;
  const distillations = [];
  const catalogue = createServer((request, response) => {
    const url = new URL(request.url, "http://fixture");
    const resource = allMedia.find((item) => url.pathname.includes(item.reference));
    response.setHeader("Content-Type", "application/json");
    if (url.pathname === "/api/assistants/tasks/transcription_pipeline/run" && request.method === "POST") {
      let body = "";
      request.on("data", (chunk) => { body += chunk; });
      request.on("end", () => distillations.push({ input: JSON.parse(body).input, response }));
    } else if (url.pathname === "/api/shared-media") {
      response.end(JSON.stringify(allMedia));
    } else if (url.pathname.endsWith("/content")) {
      if (transcriptMissing) { response.writeHead(410); response.end(); }
      else if (url.pathname.includes(first.reference)) {
        // The first selection settles late, after a subsequent selection.
        setTimeout(() => response.end("<script>unsafe()</script> First transcript"), 150);
      } else if (resource?.kind === "image" || resource?.kind === "audio") {
        response.setHeader("Content-Type", resource.content_type);
        response.setHeader("Content-Disposition", `attachment; filename="${resource.name}"`);
        response.setHeader("X-Content-Type-Options", "nosniff");
        response.end(resource.kind === "image" ? png : wav);
      } else response.end(JSON.stringify({ segments: [{ text: "Second transcript" }] }));
    } else response.end(JSON.stringify(resource));
  });
  catalogue.listen(0, "127.0.0.1");
  await once(catalogue, "listening");
  const window = new BrowserWindow({ show: false, width: 1000, height: 700, webPreferences: {
    sandbox: true, contextIsolation: true, nodeIntegration: false,
    preload: fileURLToPath(new URL("../workspace-preload.cjs", import.meta.url)),
  } });
  const workspace = new DesktopWorkspace(window, () => {}, undefined,
    createMediaReader(() => `http://127.0.0.1:${catalogue.address().port}`));
  try {
    await until(() => window.webContents.executeJavaScript("Boolean(document.getElementById('langfuse') && window.desktopWorkspace)").catch(() => false));
    await workspace.chat.webContents.loadURL("data:text/html,<input id='chat'>");
    await window.webContents.executeJavaScript("document.getElementById('media').click()");
    await until(() => window.webContents.executeJavaScript("document.querySelectorAll('#media-list button').length === 6"));
    assert.equal(workspace.active, "media");
    assert.equal(workspace.currentContents(), window.webContents);
    assert.equal(await window.webContents.executeJavaScript("document.querySelector('#media-list img') === null"), true);
    await window.webContents.executeJavaScript("document.querySelectorAll('#media-list button')[0].click(); document.querySelectorAll('#media-list button')[1].click()");
    await until(() => window.webContents.executeJavaScript("document.getElementById('media-content').textContent.includes('Second transcript')"));
    await delay(250);
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-content').textContent.includes('First transcript')"), false);
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distillation').hidden"), false);
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distill').disabled"), false);
    await window.webContents.executeJavaScript("document.getElementById('media-distill').click(); document.getElementById('media-distill').click()");
    await until(() => distillations.length === 1);
    assert.match(distillations[0].input, /Second transcript/);
    assert(distillations[0].input.includes(second.reference));
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distill').disabled"), true);
    assert.match(await window.webContents.executeJavaScript("document.getElementById('media-distill-status').textContent"), /Distilling/);
    await window.webContents.executeJavaScript("document.querySelectorAll('#media-list button')[0].click()");
    await until(() => window.webContents.executeJavaScript("document.getElementById('media-content').textContent.includes('First transcript')"));
    const distilled = "# Source reference\n\n## Reference notes\n- Preserve the supplied condition.\n<script>window.unsafeDistillation = true</script>";
    distillations[0].response.end(JSON.stringify({ ok: true, result: distilled }));
    await delay(150);
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distill-output').textContent"), "");
    await window.webContents.executeJavaScript("document.querySelectorAll('#media-list button')[1].click()");
    await until(() => window.webContents.executeJavaScript("document.getElementById('media-distill-output').textContent.includes('Preserve the supplied condition')"));
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distill-output').textContent"), distilled);
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distill-output').children.length"), 0);
    assert.equal(await window.webContents.executeJavaScript("Boolean(window.unsafeDistillation)"), false);
    assert.equal(distillations.length, 1, "duplicate clicks do not create another model run");
    await until(() => window.webContents.executeJavaScript("!document.getElementById('media-distill').disabled"));
    await window.webContents.executeJavaScript("document.getElementById('media-distill').click()");
    await until(() => distillations.length === 2);
    distillations[1].response.end(JSON.stringify({ ok: false, error: "private backend detail" }));
    await until(() => window.webContents.executeJavaScript("document.getElementById('media-distill').textContent === 'Retry distillation'"));
    assert.match(await window.webContents.executeJavaScript("document.getElementById('media-distill-status').textContent"), /Distillation failed/);
    assert.doesNotMatch(await window.webContents.executeJavaScript("document.getElementById('media-distill-status').textContent"), /private/);
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distill-output').textContent"), distilled);
    await window.webContents.executeJavaScript("document.getElementById('media-distill').click()");
    await until(() => distillations.length === 3);
    distillations[2].response.end(JSON.stringify({ ok: true, result: "# Retried reference\n\n## Source and scope\nFixture transcript.\n\n## Reference notes\n- Preserve the source's condition and uncertainty." }));
    await until(() => window.webContents.executeJavaScript("document.getElementById('media-distill-output').textContent.includes('Retried reference')"));
    await window.webContents.executeJavaScript("const search = document.getElementById('media-search'); search.value = 'vod:fixture'; search.dispatchEvent(new Event('input'))");
    assert.equal(await window.webContents.executeJavaScript("document.querySelectorAll('#media-list button').length"), 1);
    workspace.select("chat");
    workspace.select("media");
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-search').value"), "vod:fixture");
    assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-title').textContent"), "segments.json");
    assert.match(await window.webContents.executeJavaScript("document.getElementById('media-distill-output').textContent"), /Retried reference/);
    if (process.env.CHATTFT_TEST_MEDIA_SCREENSHOT) {
      // Let Chromium paint the retained result after the tab switch before
      // capturing; DOM assertions can otherwise precede the compositor frame.
      await delay(250);
      writeFileSync(process.env.CHATTFT_TEST_MEDIA_SCREENSHOT, (await window.webContents.capturePage()).toPNG());
    }
    transcriptMissing = true;
    await window.webContents.executeJavaScript("document.querySelector('#media-list button').click()");
    await until(() => window.webContents.executeJavaScript("!document.getElementById('media-retry').hidden"));
    assert.match(await window.webContents.executeJavaScript("document.getElementById('media-status').textContent"), /missing/);
    transcriptMissing = false;
    await window.webContents.executeJavaScript("document.getElementById('media-retry').click()");
    await until(() => window.webContents.executeJavaScript("document.getElementById('media-content').textContent.includes('Second transcript')"));
    await window.webContents.executeJavaScript("document.getElementById('media-search').value = ''; document.getElementById('media-search').dispatchEvent(new Event('input'))");
    for (const resource of otherMedia) {
      await window.webContents.executeJavaScript(`document.getElementById('media-kind').value = ${JSON.stringify(resource.kind)}; document.getElementById('media-kind').dispatchEvent(new Event('change'))`);
      const index = resource.kind === "data" ? 1 : 0;
      await window.webContents.executeJavaScript(`document.querySelectorAll('#media-list button')[${index}].click()`);
      await until(() => window.webContents.executeJavaScript(`document.getElementById('media-reference').value === ${JSON.stringify(resource.reference)} && document.getElementById('media-status').textContent !== 'Loading preview…'`));
      assert.equal(await window.webContents.executeJavaScript("document.getElementById('media-distillation').hidden"), true);
      await window.webContents.executeJavaScript("document.getElementById('media-copy').click()");
      await until(() => copiedReference === resource.reference);
      if (resource.kind === "image") {
        await until(() => window.webContents.executeJavaScript("document.querySelector('#media-preview img')?.naturalWidth === 1"));
      } else if (["audio", "video"].includes(resource.kind)) {
        assert.equal(await window.webContents.executeJavaScript(`document.querySelector('#media-preview ${resource.kind}').controls`), true);
        if (resource.kind === "audio") {
          await until(() => window.webContents.executeJavaScript("document.querySelector('#media-preview audio').readyState >= 1"));
          await window.webContents.executeJavaScript("window.pauseObserved = false; document.querySelector('#media-preview audio').pause = () => { window.pauseObserved = true; }; undefined");
          workspace.select("chat");
          await until(() => window.webContents.executeJavaScript("window.pauseObserved"));
          workspace.select("media");
        }
      } else assert.match(await window.webContents.executeJavaScript("document.getElementById('media-status').textContent"), /Preview unavailable/);
    }
    await window.webContents.executeJavaScript("document.getElementById('media-kind').value = ''; document.getElementById('media-kind').dispatchEvent(new Event('change'))");
    assert.equal(await window.webContents.executeJavaScript("document.querySelectorAll('#media-list button').length"), 6);
    workspace.select("chat");
    console.log("PASS: all media kinds, safe distillation output, per-source results, duplicate prevention, retry, retained state and previews");
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
    catalogue.closeAllConnections();
    await new Promise((resolve) => catalogue.close(resolve));
    clipboard.writeText = writeClipboard;
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
