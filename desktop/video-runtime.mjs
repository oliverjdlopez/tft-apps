/** Attach to compatible video services or own the missing processes. */
import os from "node:os";
import { DesktopRuntime } from "./runtime.mjs";
import { probeVideoService, waitForHttp, waitForIdentity, waitForRecord } from "./utils.mjs";

/** Manage one VOD checkout independently of ChatTFT and the other video workspace. */
export class VideoRuntime extends DesktopRuntime {
  /**
   * Select fixed workspace ports and a checkout-specific Python environment.
   * Args:
   *   root: ChatTFT checkout; node: service Node; options: launcher options;
   *   wsl: Optional original Linux environment; tab: vod or wisps.
   */
  constructor(root, node, options, wsl, tab) {
    super(root, node, options, wsl);
    this.tab = tab;
    const env = wsl?.env ?? process.env;
    const home = wsl ? env.HOME : os.homedir();
    const override = env[tab === "wisps" ? "CHATTFT_WISPS_REPO" : "CHATTFT_VOD_REPO"];
    if (!home && !override) throw new Error("Video checkout home directory is unavailable.");
    this.repo = override ?? this.paths.join(home, tab === "wisps" ? "vod-review-wt2" : "vod-review");
    this.backendPort = tab === "wisps" ? 8001 : 8000;
    this.frontendPort = tab === "wisps" ? 5175 : 5174;
    this.python = this.paths.join(this.repo, ".venv", !wsl && process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  }

  /**
   * Reuse verified services, starting only absent ones with existing ownership rules.
   * Returns:
   *   The ready frontend URL; rejects after cleaning up only newly owned children.
   */
  async start() {
    this.state = "starting";
    const signal = this.controller.signal;
    const timer = setTimeout(() => this.controller.abort(new Error("Video workspace startup timed out.")), this.options.startupTimeout);
    const backendUrl = `http://127.0.0.1:${this.backendPort}`;
    const frontendUrl = `http://127.0.0.1:${this.frontendPort}`;
    try {
      // Probe both ports before spawning anything. An occupied incompatible port
      // is an error, never a reason to stop another application's process.
      const backend = await probeVideoService(backendUrl, "backend", this.tab, signal);
      const frontend = await probeVideoService(frontendUrl, "frontend", this.tab, signal);
      if (!backend) {
        const child = this.spawn(this.python, ["-u", this.paths.join(this.root, "desktop/vod_backend.py"),
          "--repo", this.repo, "--port", String(this.backendPort)], `${this.tab} backend`);
        await waitForRecord(child, "bound", signal);
        if (this.wsl) await waitForIdentity(backendUrl, this.identity, signal);
        await waitForHttp(`${backendUrl}/api/health`, signal);
        if (!await probeVideoService(backendUrl, "backend", this.tab, signal)) throw new Error("Video backend disappeared during startup.");
      }
      if (!frontend) {
        const args = [this.paths.join(this.root, "desktop/vod-frontend.mjs"), "--repo", this.repo, "--managed"];
        if (this.tab === "wisps") args.push("--wisps");
        const child = this.spawn(this.node, args, `${this.tab} frontend`);
        await waitForRecord(child, "listening", signal);
        if (this.wsl) await waitForIdentity(frontendUrl, this.identity, signal);
        if (!await probeVideoService(frontendUrl, "frontend", this.tab, signal)) throw new Error("Video frontend disappeared during startup.");
      }
      signal.throwIfAborted();
      this.state = "running";
      return frontendUrl;
    } catch (error) {
      await this.stop();
      throw error;
    } finally { clearTimeout(timer); }
  }
}
