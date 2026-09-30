/** Own the checkout services for one Electron application lifetime. */
import { EventEmitter } from "node:events";
import path from "node:path";
import { launcherPaths } from "./paths.mjs";
import { randomUUID } from "node:crypto";
import { abortable, ownedProcess, processFailure, stopProcess, waitForHttp, waitForRecord, wslCommand, waitForIdentity, serviceEnvironment } from "./utils.mjs";

/** Coordinate frontend builds, service readiness, cancellation, and shutdown. */
export class DesktopRuntime extends EventEmitter {
  /**
   * Configure the checkout without starting any child processes.
   * Args:
   *   root: Repository root; node: service Node executable; options: validated CLI;
   *   wsl: Optional Linux environment supplied by the WSL bootstrap.
   */
  constructor(root, node, options, wsl) {
    super();
    this.root = root;
    this.node = node;
    this.options = options;
    this.wsl = wsl;
    this.paths = wsl ? path.posix : path;
    this.roots = launcherPaths(root, this.paths);
    this.cwd = this.roots.chat;
    this.identity = randomUUID();
    this.children = [];
    this.controller = new AbortController();
    this.state = "idle";
  }

  /**
   * Start current frontend sources and the existing backend, then await HTTP.
   * Returns:
   *   The owned frontend URL; rejects on failure or timeout after cleanup.
   */
  async start() {
    this.state = "starting";
    const signal = this.controller.signal;
    const timer = setTimeout(() => this.controller.abort(new Error(
      this.wsl
        ? "WSL startup timed out. Check the launch terminal, Windows-to-WSL localhost forwarding, and port conflicts; increase --startup-timeout for slow startup."
        : "Startup timed out. Check the launch terminal and configuration, or increase --startup-timeout (seconds).",
    )), this.options.startupTimeout);
    try {
      if (this.options.mode === "production") {
        this.emit("progress", "Building the current frontend…");
        const build = this.spawn(this.node, [this.paths.join(this.roots.desktop, "frontend.mjs"), "production"], "Frontend build", true);
        const result = await abortable(build.finished, signal);
        if (result.code !== 0 || result.error) throw processFailure(build);
      }
      signal.throwIfAborted();
      this.emit("progress", "Starting the Python backend…");
      const args = ["-u", this.paths.join(this.roots.desktop, "backend.py")];
      if (this.options.port !== undefined) args.push("--port", String(this.options.port));
      const backend = this.spawn(this.options.python, args, "Python backend");
      const bound = await waitForRecord(backend, "bound", signal);
      if (!Number.isInteger(bound.port) || bound.port < 1 || bound.port > 65535) throw new Error("Backend reported an invalid port.");
      const backendUrl = `http://127.0.0.1:${bound.port}`;
      if (this.wsl) await waitForIdentity(backendUrl, this.identity, signal);
      // The bound event precedes probes so an unrelated server cannot satisfy
      // readiness when the requested backend failed to acquire its socket.
      await waitForHttp(`${backendUrl}/api/config`, signal);
      let frontendUrl = backendUrl;
      if (this.options.mode === "dev") {
        this.emit("progress", "Starting frontend hot reload…");
        const frontend = this.spawn(this.node, [this.paths.join(this.roots.desktop, "frontend.mjs"), "dev", String(this.options.devPort), String(bound.port)], "Vite development server");
        await waitForRecord(frontend, "listening", signal);
        frontendUrl = `http://127.0.0.1:${this.options.devPort}`;
        if (this.wsl) await waitForIdentity(frontendUrl, this.identity, signal);
      }
      this.emit("progress", "Waiting for the application…");
      await waitForHttp(frontendUrl, signal);
      signal.throwIfAborted();
      this.state = "running";
      return frontendUrl;
    } catch (error) {
      await this.stop();
      throw error;
    } finally { clearTimeout(timer); }
  }

  /**
   * Register one child and propagate unexpected exits into runtime failure.
   * Args:
   *   command: Native executable; args: argument array; label: status label;
   *   finite: whether successful completion is expected before app launch.
   * Returns:
   *   Owned child handle.
   */
  spawn(command, args, label, finite = false) {
    // Quit may have occurred while the previous readiness response was settling.
    // Never create a child after stop() has snapshotted the owned processes.
    this.controller.signal.throwIfAborted();
    const service = { command, args, cwd: this.cwd, env: { ...serviceEnvironment(this.wsl?.env ?? process.env, this.roots, this.cwd, this.paths), CHATTFT_DESKTOP_IDENTITY: this.identity } };
    const invocation = this.wsl ? wslCommand(this.wsl) : { command, args, cwd: this.cwd };
    const handle = ownedProcess(invocation.command, invocation.args, { cwd: invocation.cwd, env: service.env, label, onExit: (child) => {
      if (child.stopping || this.state === "stopping" || this.state === "stopped" || finite) return;
      const error = processFailure(child);
      this.controller.abort(error);
      if (this.state === "running") this.emit("failure", error);
    } });
    if (this.wsl) handle.child.stdin.write(`${JSON.stringify(service)}\n`);
    this.children.push(handle);
    return handle;
  }

  /** Stop owned services once, including when quit races with startup failure. */
  async stop() {
    if (this.stopPromise) return this.stopPromise;
    this.state = "stopping";
    this.controller.abort(new Error("Desktop is shutting down."));
    this.stopPromise = Promise.allSettled(this.children.map((child) => stopProcess(child, this.wsl ? 20000 : 12000))).then((results) => {
      this.state = "stopped";
      const failures = results.filter((result) => result.status === "rejected");
      if (failures.length) throw new Error("A desktop service could not be stopped. Check the launch terminal before restarting.");
    });
    return this.stopPromise;
  }
}
