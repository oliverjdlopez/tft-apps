/** Prepare and launch Windows Electron without Windows backend dependencies. */
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { copyFile, mkdir, readFile, access } from "node:fs/promises";
import path from "node:path";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { createParentPipe, electronExecutable, stageWindowsShell } from "./utils.mjs";

let child;
let lifetime;
let stopping = false;
const parent = createInterface({ input: process.stdin });
parent.once("line", (line) => main(JSON.parse(line)).catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
  lifetime?.close();
  parent.close();
  process.stdin.destroy();
}));
parent.on("line", (line) => { if (line === "shutdown") stop(); });
parent.on("close", stop);

/** Forward terminal loss and Ctrl+C without letting an orphan shell keep running. */
function stop() {
  stopping = true;
  lifetime?.shutdown();
  child?.stdin?.end("shutdown\n");
}

/**
 * Install only on explicit setup, then run a refreshed copy of desktop shell code.
 * Args:
 *   context: Linux checkout and environment received over the bootstrap pipe.
 */
async function main(context) {
  if (process.platform !== "win32") throw new Error("The WSL desktop shell requires a Windows node.exe.");
  const [major, minor] = process.versions.node.split(".").map(Number);
  if (major !== 22 || minor < 12) throw new Error("Install Windows Node 22.12+ within Node 22, or select it using --windows-node.");
  const source = path.dirname(fileURLToPath(import.meta.url));
  const lock = await readFile(path.join(source, "package-lock.json"));
  const version = createHash("sha256").update(lock).digest("hex").slice(0, 16);
  const cache = path.join(process.env.LOCALAPPDATA, "ChatTFT Desktop", "runtime", `${process.arch}-${version}`);
  if (context.setup) {
    const npm = path.join(path.dirname(process.execPath), "node_modules/npm/bin/npm-cli.js");
    try { await access(npm); } catch { throw new Error("Windows Node must include npm. Install the standard Windows Node 22 distribution."); }
    await mkdir(cache, { recursive: true });
    await copyFile(path.join(source, "package.json"), path.join(cache, "package.json"));
    await copyFile(path.join(source, "package-lock.json"), path.join(cache, "package-lock.json"));
    if (stopping) return;
    console.log(`Installing Windows Electron in ${cache}`);
    child = spawn(process.execPath, [npm, "ci", "--no-audit", "--no-fund"], {
      cwd: cache, env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined,
        PATH: `${path.dirname(process.execPath)};${process.env.PATH ?? ""}` }, shell: false,
      stdio: ["pipe", "inherit", "inherit"], windowsHide: true,
    });
  } else {
    const electron = await electronExecutable(cache);
    // Each launch stages only shell code. React, Python, configuration, and all
    // native Linux node_modules remain in the checkout and are never copied.
    const staged = await stageWindowsShell(source, cache);
    if (stopping) return;
    lifetime = await createParentPipe();
    if (stopping) { lifetime.close(); return; }
    const env = { ...process.env, CHATTFT_DESKTOP_WSL: JSON.stringify(context), CHATTFT_DESKTOP_PARENT_PIPE: lifetime.name };
    delete env.ELECTRON_RUN_AS_NODE;
    child = spawn(electron, [staged], { cwd: cache, env, shell: false, stdio: ["ignore", "inherit", "inherit"] });
  }
  child.stdin?.on("error", () => {});
  child.on("error", (error) => { console.error(error.message); process.exitCode = 1; lifetime?.close(); parent.close(); process.stdin.destroy(); });
  child.on("exit", (code) => { process.exitCode = code ?? 1; lifetime?.close(); parent.close(); process.stdin.destroy(); });
}
