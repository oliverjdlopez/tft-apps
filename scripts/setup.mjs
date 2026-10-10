/** Install the native shell and build independent Docker application images. */
import { fileURLToPath } from "node:url";
import path from "node:path";
import { buildImages, run } from "../desktop/docker.mjs";

/** Validate host tools and prepare dependencies without starting applications. */
async function main() {
  const [major, minor] = process.versions.node.split(".").map(Number);
  if (major !== 22 || minor < 12) throw new Error("Use Node 22.12 or later within Node 22.");
  const root = fileURLToPath(new URL("../", import.meta.url));
  await run("docker", ["info", "--format", "{{.ServerVersion}}"]);
  await run("docker", ["compose", "version"]);
  await run(process.platform === "win32" ? "npm.cmd" : "npm", ["ci", "--no-audit", "--no-fund"], { cwd: path.join(root, "desktop") });
  await buildImages(root);
  console.log("Images and desktop ready. Run npm start or npm run dev from desktop/. VOD requires Docker GPU access; TFT_DOCKER_GPU=0 selects CPU mode.");
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
