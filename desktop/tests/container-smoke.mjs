/** Opt-in real Docker acceptance with disposable data and no model/database keys. */
import assert from "node:assert/strict";
import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { once } from "node:events";
import { DesktopRuntime } from "../runtime.mjs";
import { VideoRuntime } from "../video-runtime.mjs";
import { run, SUITE_ROOT } from "../docker.mjs";

/** Find a disposable port without adopting an existing application listener. */
async function freePort() {
  const server = net.createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return port;
}

/** Exercise image startup, development proxies, mounted state and owned shutdown. */
async function main() {
  const root = await mkdtemp(path.join(os.tmpdir(), "tft-container-smoke-"));
  const active = [];
  for (const key of Object.keys(process.env)) {
    if (/^(RDS_|AWS_|OPENAI_|ANTHROPIC_|RIOT_|CHAT_TFT_|VOD_|LANGFUSE_)/.test(key)) delete process.env[key];
  }
  process.env.TFT_DOCKER_GPU = "0";
  process.env.HOME = path.join(root, "host-home");
  try {
    for (const app of ["desktop", "tft-chat", "vod-review"]) await mkdir(path.join(root, app));
    for (const file of ["container-worker.mjs", "docker.mjs", "utils.mjs", "paths.mjs"]) {
      await copyFile(path.join(SUITE_ROOT, "desktop", file), path.join(root, "desktop", file));
    }
    // Keep source-derived dev proxy configuration current while retaining all
    // installed dependencies and frontend source inside the built images.
    for (const [directory, file] of [["tft-chat/app/frontend", "vite.config.js"], ["vod-review/frontend", "vite.config.ts"]]) {
      await mkdir(path.join(root, directory), { recursive: true });
      await copyFile(path.join(SUITE_ROOT, directory, file), path.join(root, directory, file));
    }
    for (const service of ["chat", "vod"]) {
      for (const mode of ["production", "dev"]) {
        const options = { mode, port: await freePort(), devPort: await freePort(), startupTimeout: 120000 };
        const runtime = service === "chat" ? new DesktopRuntime(root, process.execPath, options) : new VideoRuntime(root, process.execPath, options);
        if (service === "vod") { runtime.backendPort = options.port; runtime.frontendPort = options.devPort; }
        active.push(runtime);
        const origin = await runtime.start();
        const html = await fetch(origin);
        assert.equal(html.status, 200);
        assert.match(await html.text(), /<html/i);
        const identity = await fetch(`${origin}/__chattft_desktop__/identity`);
        assert.equal(identity.headers.get("x-chattft-desktop-identity"), runtime.identity);
        const project = `tft-apps-${service}-${runtime.identity}`;
        const container = await run("docker", ["ps", "-q", "--filter", `label=com.docker.compose.project=${project}`, "--filter", `label=com.docker.compose.service=${service}`], { capture: true });
        assert(container && !container.includes("\n"));
        const marker = service === "vod" ? `${root}/vod-review/data/mount-check.txt` : `${root}/media/mount-check.txt`;
        await writeFile(marker, "host-visible");
        await run("docker", ["exec", container, "python", "-c", "import pathlib,sys; p=pathlib.Path(sys.argv[1]); assert p.read_text()=='host-visible'; p.write_text('container-visible')", marker]);
        assert.equal(await readFile(marker, "utf8"), "container-visible");
        if (service === "vod") assert.equal((await fetch(`${origin}/api/not-a-route`)).status, 404);
        await runtime.stop();
        assert.equal(await run("docker", ["ps", "-aq", "--filter", `label=com.docker.compose.project=${project}`], { capture: true }), "");
        assert.equal(await readFile(marker, "utf8"), "container-visible");
        console.log(`PASS ${service} ${mode}: HTTP, identity, local storage and cleanup`);
      }
    }
  } finally {
    const results = await Promise.allSettled(active.map((runtime) => runtime.stop()));
    if (results.some((result) => result.status === "rejected")) throw new Error(`Cleanup failed; inspect disposable checkout ${root}`);
    await rm(root, { recursive: true, force: true });
  }
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
