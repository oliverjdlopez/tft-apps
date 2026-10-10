/** Own the VOD container project for the persistent VOD Review view. */
import { DesktopRuntime } from "./runtime.mjs";

/** Manage the suite-local video application without adopting external services. */
export class VideoRuntime extends DesktopRuntime {
  /**
   * Select the VOD container service and its fixed application ports.
   * Args:
   *   root: Suite root; node: service Node; options: validated launcher options.
   *   wsl: Optional original Linux launch context.
   */
  constructor(root, node, options, wsl) {
    super(root, node, options, wsl);
    this.repo = this.roots.vod;
    this.cwd = this.repo;
    this.service = "vod";
    this.backendPort = 8000;
    this.frontendPort = 5174;
    this.healthPath = "/api/health";
  }
}
