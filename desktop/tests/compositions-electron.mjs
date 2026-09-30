/** Exercise the production Compositions page against an isolated real API worker. */
import { app, BrowserWindow } from "electron";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { setTimeout as delay } from "node:timers/promises";
const profile = mkdtempSync(path.join(os.tmpdir(), "composition-ui-smoke-"));
app.setPath("userData", profile);
app.setPath("sessionData", profile);
app.on("window-all-closed", () => {});
/** Wait for a native rendered condition with a finite operation deadline. */
async function until(contents, expression) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    if (await contents.executeJavaScript(expression)) return;
    await delay(100);
  }
  throw new Error(`Timed out: ${expression}`);
}
/** Validate form submission, worker polling, saved results and diagnostic rendering. */
async function run() {
  await app.whenReady();
  const window = new BrowserWindow({
    show: false,
    width: 1400,
    height: 1000,
    webPreferences: {
      sandbox: true,
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  const contents = window.webContents;
  const errors = [];
  contents.on("console-message", (_event, level, message) => {
    if (level === 3) errors.push(message);
  });
  try {
    await contents.loadURL(
      process.env.CHATTFT_COMPOSITION_SMOKE_URL ||
        "http://127.0.0.1:58341/compositions",
    );
    await until(
      contents,
      "document.querySelectorAll('form select')[0]?.options.length === 5",
    );
    await contents.executeJavaScript(
      `(()=>{const select=document.querySelectorAll('form select')[1]; const setter=Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set; setter.call(select,'fixture');select.dispatchEvent(new Event('change',{bubbles:true}));})()`,
    );
    await contents.executeJavaScript(
      "document.querySelector('form').requestSubmit()",
    );
    await until(
      contents,
      "Array.from(document.querySelectorAll('[role=status]')).some(el=>el.textContent.startsWith('completed'))",
    );
    assert.equal(
      await contents.executeJavaScript(
        "document.querySelectorAll('[role=alert]').length",
      ),
      0,
    );
    await until(
      contents,
      "document.querySelector('[aria-label=\"Experiment families\"] button') !== null",
    );
    await contents.executeJavaScript(
      "document.querySelector('[aria-label=\"Experiment families\"] button').click()",
    );
    await until(
      contents,
      "document.body.innerText.includes('Family definition')",
    );
    assert.equal(
      await contents.executeJavaScript("typeof window.require"),
      "undefined",
    );
    assert.equal(
      await contents.executeJavaScript(
        "document.body.innerText.includes('Representative board')",
      ),
      true,
    );
    await contents.executeJavaScript(
      "Array.from(document.querySelectorAll('details')).find(el=>el.querySelector('summary')?.textContent.includes('HDBSCAN cluster persistence')).open=true",
    );
    await until(
      contents,
      "document.querySelector('details[open] table tbody tr') !== null",
    );
    if (process.env.CHATTFT_COMPOSITION_SCREENSHOT)
      writeFileSync(
        process.env.CHATTFT_COMPOSITION_SCREENSHOT,
        (await contents.capturePage()).toPNG(),
      );
    const historyRows = await contents.executeJavaScript(
      "document.querySelector('table tbody').children.length",
    );
    await contents.reload();
    await until(
      contents,
      `document.querySelector('table tbody')?.children.length >= ${historyRows}`,
    );
    assert.equal(errors.length, 0, errors.join("\n"));
    console.log(
      "PASS: production React page, five parameter schemas, real queued worker, family display, diagnostics, saved history after reload, renderer isolation",
    );
  } finally {
    window.destroy();
  }
}
run().then(
  () => app.exit(0),
  (error) => {
    console.error(error);
    app.exit(1);
  },
);
app.on("quit", () => {
  try {
    rmSync(profile, { recursive: true, force: true });
  } catch {}
});
