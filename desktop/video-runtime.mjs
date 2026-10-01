/** Own one VOD backend and frontend for VOD Review. */
import { DesktopRuntime } from "./runtime.mjs";
import { assertPortAvailable, waitForHttp, waitForIdentity, waitForRecord } from "./utils.mjs";

/** Manage the suite-local video application without adopting external services. */
export class VideoRuntime extends DesktopRuntime {
  /**
   * Select the independent VOD environment and shared fixed application ports.
   * Args:
   *   root: Suite root; node: service Node; options: validated launcher options.
   *   wsl: Optional original Linux launch context.
   */
  constructor(root, node, options, wsl) {
    super(root, node, options, wsl);
    this.repo = this.roots.vod;
    this.cwd = this.repo;
    this.backendPort = 8000;
    this.frontendPort = 5174;
    this.python = this.paths.join(this.repo, ".venv", !wsl && process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  }

  /** Return one readiness promise so concurrent requests cannot spawn duplicates. */
  start() {
    this.startPromise ??= this.startServices();
    return this.startPromise;
  }

  /** Start both owned services, verify identity and readiness, and clean up failure. */
  async startServices() {
    this.state = "starting";
    const signal = this.controller.signal;
    const timer = setTimeout(() => this.controller.abort(new Error("Video workspace startup timed out.")), this.options.startupTimeout);
    const backendUrl = `http://127.0.0.1:${this.backendPort}`;
    const frontendUrl = `http://127.0.0.1:${this.frontendPort}`;
    try {
      // On WSL the Linux workers bind strictly; Windows readiness also checks
      // the per-launch identity. Neither side can adopt an original checkout.
      if (!this.wsl) {
        await assertPortAvailable(this.backendPort);
        await assertPortAvailable(this.frontendPort);
      }
      signal.throwIfAborted();
      const backend = this.spawn(this.python, ["-u", this.paths.join(this.roots.desktop, "vod_backend.py"),
        "--repo", this.repo, "--port", String(this.backendPort)], "VOD backend");
      await waitForRecord(backend, "bound", signal);
      await waitForIdentity(backendUrl, this.identity, signal);
      await waitForHttp(`${backendUrl}/api/health`, signal);
      const frontend = this.spawn(this.node, [this.paths.join(this.roots.desktop, "vod-frontend.mjs"),
        "--repo", this.repo, "--managed", "--port", String(this.frontendPort),
        "--backend-port", String(this.backendPort)], "VOD frontend");
      await waitForRecord(frontend, "listening", signal);
      await waitForIdentity(frontendUrl, this.identity, signal);
      await waitForHttp(frontendUrl, signal);
      signal.throwIfAborted();
      this.state = "running";
      return frontendUrl;
    } catch (error) {
      await this.stop();
      throw error;
    } finally { clearTimeout(timer); }
  }
}
