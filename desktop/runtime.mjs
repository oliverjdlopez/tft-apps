/** Own the checkout services for one Electron application lifetime. */
import { EventEmitter } from "node:events";
import path from "node:path";
import { launcherPaths } from "./paths.mjs";
import { randomUUID } from "node:crypto";
import { assertPortAvailable, ownedProcess, processFailure, stopProcess, waitForHttp, waitForRecord, wslCommand, waitForIdentity, serviceEnvironment } from "./utils.mjs";

/** Coordinate an owned container worker, readiness, cancellation, and shutdown. */
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
    this.service = "chat";
    this.backendPort = options.port ?? 8300;
    this.frontendPort = options.mode === "dev" ? (options.devPort ?? 5173) : this.backendPort;
    this.healthPath = "/api/config";
    this.identity = randomUUID();
    this.children = [];
    this.controller = new AbortController();
    this.state = "idle";
  }

  /**
   * Share one container startup across concurrent requests for this application.
   * Returns:
   *   The owned frontend URL; rejects on failure or timeout after cleanup.
   */
  start() {
    this.startPromise ??= this.startServices();
    return this.startPromise;
  }

  /** Start the app's container worker and verify both owned HTTP endpoints. */
  async startServices() {
    this.state = "starting";
    const signal = this.controller.signal;
    const timer = setTimeout(() => this.controller.abort(new Error(
      this.wsl
        ? "WSL startup timed out. Check the launch terminal, Windows-to-WSL localhost forwarding, and port conflicts; increase --startup-timeout for slow startup."
        : "Startup timed out. Check the launch terminal and configuration, or increase --startup-timeout (seconds).",
    )), this.options.startupTimeout);
    try {
      if (!this.wsl) {
        // Refuse another checkout's listener before starting our own project.
        // The worker also enforces ownership on the Docker/WSL side.
        for (const port of new Set([this.backendPort, this.frontendPort])) {
          await assertPortAvailable(port);
          signal.throwIfAborted();
        }
      }
      signal.throwIfAborted();
      const label = this.service === "chat" ? "ChatTFT containers" : "VOD containers";
      this.emit("progress", `Starting ${label}…`);
      const worker = this.spawn(this.node, [this.paths.join(this.roots.desktop, "container-worker.mjs"),
        "--service", this.service, "--mode", this.options.mode ?? "production",
        "--backend-port", String(this.backendPort), "--frontend-port", String(this.frontendPort),
        "--identity", this.identity], label);
      const bound = await waitForRecord(worker, "bound", signal);
      if (bound.port !== this.backendPort) throw new Error("Container worker reported an unexpected backend port.");
      const backendUrl = `http://127.0.0.1:${this.backendPort}`;
      await waitForIdentity(backendUrl, this.identity, signal);
      await waitForHttp(`${backendUrl}${this.healthPath}`, signal);
      const listening = await waitForRecord(worker, "listening", signal);
      if (listening.port !== this.frontendPort) throw new Error("Container worker reported an unexpected frontend port.");
      const frontendUrl = `http://127.0.0.1:${this.frontendPort}`;
      if (frontendUrl !== backendUrl) {
        await waitForIdentity(frontendUrl, this.identity, signal);
      }
      this.emit("progress", "Waiting for the application…");
      await waitForHttp(frontendUrl, signal);
      signal.throwIfAborted();
      this.state = "running";
      return frontendUrl;
    } catch (error) {
      // HTTP retry delays throw AbortError; retain the worker's concrete failure
      // or startup timeout that cancelled those probes before stop() runs.
      const failure = signal.aborted ? signal.reason : error;
      await this.stop();
      throw failure;
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
    // The Windows wrapper needs its native PATH to find wsl.exe; the Linux
    // service environment travels only through the guardian pipe below.
    const handle = ownedProcess(invocation.command, invocation.args, { cwd: invocation.cwd, env: this.wsl ? process.env : service.env, label, onExit: (child) => {
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
    this.stopPromise = Promise.allSettled(this.children.map(async (child) => {
      // Compose must finish tearing down its project before a retry can own the
      // same ports. A killed guardian does not prove its containers were stopped.
      await stopProcess(child, 60000);
      if (child.records.has("cleanup_error") || child.result?.signal === "SIGKILL") {
        throw new Error("Container cleanup did not complete.");
      }
    })).then((results) => {
      this.state = "stopped";
      const failures = results.filter((result) => result.status === "rejected");
      if (failures.length) throw new Error("A desktop service could not be stopped. Check the launch terminal before restarting.");
    });
    return this.stopPromise;
  }
}
