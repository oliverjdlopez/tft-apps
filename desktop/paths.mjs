/** Resolve the suite and independently installed applications for every launcher. */
import path from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Resolve launcher roots independently of the invoking terminal directory.
 * Args:
 *   suite: Suite location, optionally supplied by the original WSL process.
 *   paths: Host path implementation; Windows-to-WSL services use path.posix.
 * Returns:
 *   Absolute suite, desktop, ChatTFT and VOD application roots.
 */
export function launcherPaths(suite = fileURLToPath(new URL("../", import.meta.url)), paths = path) {
  const root = paths.resolve(suite);
  return Object.freeze({ suite: root, desktop: paths.join(root, "desktop"),
    chat: paths.join(root, "tft-chat"), vod: paths.join(root, "vod-review") });
}
