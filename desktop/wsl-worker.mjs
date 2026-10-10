/** Keep a Linux service owned across the Windows wsl.exe process boundary. */
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { emitEvent } from "./utils.mjs";

let child;
let stopping = false;
let deadline;
const parent = createInterface({ input: process.stdin });
parent.once("line", (line) => {
  if (stopping || line === "shutdown") return;
  try { start(JSON.parse(line)); } catch {
    emitEvent("error", { message: "Could not initialize the WSL service. Relaunch from the WSL terminal." });
    process.exit(1);
  }
});
parent.on("line", (line) => { if (line === "shutdown") stop(); });
parent.on("close", stop);
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, stop);

/**
 * Run one service in its own process group with the original Linux environment.
 * Args:
 *   spec: Executable, literal argument array, and environment from the owner pipe.
 */
function start(spec) {
  // A private process group permits bounded cleanup of build subprocesses too;
  // no distro-wide shutdown or process-name-based termination is used.
  child = spawn(spec.command, spec.args, {
    cwd: spec.cwd, env: spec.env, detached: true, shell: false, stdio: ["pipe", "inherit", "inherit"],
  });
  child.stdin.on("error", () => {});
  child.on("error", () => {
    emitEvent("error", { message: "WSL container worker could not start. Check Linux Node, Docker access, and the desktop setup in this checkout." });
    process.exit(1);
  });
  child.on("exit", (code, signal) => {
    clearTimeout(deadline);
    // The service may exit before a native build subprocess finishes. The
    // process-group ID stays scoped to this service and is never reused by us.
    try { process.kill(-child.pid, "SIGKILL"); } catch { /* Group already gone. */ }
    if (signal) emitEvent("cleanup_error", { message: "The WSL container worker was terminated before confirming cleanup." });
    process.exit(signal ? 1 : stopping ? 0 : (code ?? 1));
  });
}

/** Request graceful shutdown on command/EOF, then reap only the owned group. */
function stop() {
  if (stopping) return;
  stopping = true;
  if (!child) { process.exit(0); return; }
  child.stdin.end("shutdown\n");
  deadline = setTimeout(() => {
    emitEvent("cleanup_error", { message: "Timed out stopping the WSL container worker; check owned Docker services before restarting." });
    try { process.kill(-child.pid, "SIGKILL"); } catch { /* Process already gone. */ }
    process.exit(1);
  }, 45000);
}
