/** Launch Electron with a known native Node executable and parent lifetime. */
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createParentPipe, ensureLangfuse, launchOptions } from "./utils.mjs";
import { launchFromWsl } from "./wsl.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));

/** Start the desktop shell without relying on shell-specific environment syntax. */
async function main() {
  if (process.platform === "linux" && process.env.WSL_DISTRO_NAME) {
    await launchFromWsl(process.argv.slice(2));
    return;
  }
  const args = process.argv.slice(2);
  const options = launchOptions(args, root);
  if (options.help) {
    console.log("ChatTFT desktop: npm start | npm run dev\nOptions (after --): --python PATH --port PORT --dev-port PORT --startup-timeout SECONDS");
    return;
  }
  const require = createRequire(import.meta.url);
  let electron;
  try {
    // Electron's package entry can download binaries on require(). Resolve the
    // already-installed binary directly so application startup stays offline.
    const packageRoot = path.dirname(require.resolve("electron/package.json"));
    electron = path.join(packageRoot, "dist", readFileSync(path.join(packageRoot, "path.txt"), "utf8").trim());
    if (!existsSync(electron)) throw new Error("Missing Electron binary");
  } catch {
    throw new Error("Electron is not installed. Run npm ci in desktop/, then retry.");
  }
  await ensureLangfuse(root, options.python);
  const env = { ...process.env, CHATTFT_DESKTOP_NODE: process.execPath };
  delete env.ELECTRON_RUN_AS_NODE;
  const lifetime = process.platform === "win32" ? await createParentPipe() : undefined;
  if (lifetime) env.CHATTFT_DESKTOP_PARENT_PIPE = lifetime.name;
  const child = spawn(electron, [fileURLToPath(new URL(".", import.meta.url)), ...args], {
    env, shell: false, stdio: [lifetime ? "ignore" : "pipe", "inherit", "inherit"],
  });
  child.stdin?.on("error", () => {});
  // EOF propagates even when this bootstrap is killed and cannot run a handler.
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => {
    if (lifetime) lifetime.shutdown();
    else child.stdin.end("shutdown\n");
  });
  child.on("error", (error) => { lifetime?.close(); console.error(error.message); process.exitCode = 1; });
  child.on("exit", (code) => { lifetime?.close(); process.exitCode = code ?? 1; });
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
