/** Launch a native Windows shell from the developer's existing WSL environment. */
import { execFileSync, spawn } from "node:child_process";
import { userInfo } from "node:os";
import { fileURLToPath } from "node:url";
import { ensureLangfuse, launchOptions, splitWslOptions } from "./utils.mjs";

/**
 * Resolve Windows Node and pass the Linux checkout context over a private pipe.
 * Args:
 *   args: Launch arguments, including optional Windows executable override/setup.
 *   entry: Optional Windows entry script used by the native integration tests.
 */
export async function launchFromWsl(args, entry = new URL("./windows.mjs", import.meta.url)) {
  const { setup, windowsNode, applicationArgs } = splitWslOptions(args);
  const root = fileURLToPath(new URL("../", import.meta.url)).replace(/\/$/, "");
  const options = launchOptions(applicationArgs, root);
  if (options.help) {
    console.log("WSL desktop: npm run setup:wsl (once), then npm start | npm run dev\nOptions (after --): --windows-node /mnt/c/path/node.exe --python LINUX_PATH --port PORT --dev-port PORT --startup-timeout SECONDS");
    return;
  }
  if (!process.env.WSL_DISTRO_NAME) throw new Error("Run this command in your WSL checkout using Linux Node.");
  let executable = windowsNode ?? process.env.CHATTFT_WINDOWS_NODE;
  if (!executable) {
    try {
      const native = execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
        "(Get-Command node.exe -ErrorAction Stop).Source"], { encoding: "utf8", timeout: 15000 }).trim();
      executable = execFileSync("wslpath", ["-u", native], { encoding: "utf8" }).trim();
    } catch {
      throw new Error("Windows Node was not found. Install Windows Node 22 (no Windows Python needed), reopen your WSL terminal, or set CHATTFT_WINDOWS_NODE=/mnt/c/path/to/node.exe.");
    }
  }
  const script = execFileSync("wslpath", ["-w", fileURLToPath(entry)], { encoding: "utf8" }).trim();
  // Docker and Python belong to the Linux checkout, not the Windows shell cache.
  if (!setup && entry.href === new URL("./windows.mjs", import.meta.url).href) {
    await ensureLangfuse(root, options.python);
  }
  const context = {
    root, node: process.execPath, distro: process.env.WSL_DISTRO_NAME,
    user: userInfo().username, options, env: { ...process.env }, setup,
  };
  // Environment values can include credentials; never place this record in an
  // argv, temporary file, or diagnostic. Only the native main process sees it.
  const child = spawn(executable, [script], { shell: false, stdio: ["pipe", "inherit", "inherit"] });
  child.stdin.on("error", () => {});
  child.stdin.write(`${JSON.stringify(context)}\n`);
  for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => child.stdin.end("shutdown\n"));
  child.on("error", () => {
    console.error("Could not start Windows Node. Check --windows-node and that WSL Windows interoperability is enabled.");
    process.exitCode = 1;
  });
  child.on("exit", (code) => { process.exitCode = code ?? 1; });
}
