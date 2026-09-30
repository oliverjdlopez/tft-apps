/** Run an independently installed VOD frontend with a same-origin backend proxy. */
import path from "node:path";
import os from "node:os";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { emitEvent, watchParent } from "./utils.mjs";

/**
 * Start the selected checkout's Vite server without changing its configuration.
 * Args:
 *   args: CLI arguments; --wisps selects the Wisps worktree and --repo overrides its path.
 * Returns:
 *   The listening Vite server, owned by this foreground command.
 */
export async function startVodFrontend(args = process.argv.slice(2)) {
  const { values } = parseArgs({ args, options: {
    wisps: { type: "boolean", default: false },
    managed: { type: "boolean", default: false },
    repo: { type: "string" },
  } });
  const root = path.resolve(values.repo ?? path.join(os.homedir(), values.wisps ? "vod-review-wt2" : "vod-review"));
  const frontend = path.join(root, "frontend");
  const port = values.wisps ? 5175 : 5174;
  const backendPort = values.wisps ? 8001 : 8000;
  // The existing clients accept an empty base URL. Proxying avoids widening
  // backend CORS rules and keeps video playback and uploads on the same origin.
  process.env.VITE_API_BASE = "";
  const { createServer } = await import(pathToFileURL(path.join(frontend, "node_modules/vite/dist/node/index.js")).href);
  let server;
  if (values.managed) watchParent(async () => { await server?.close(); });
  server = await createServer({
    root: frontend,
    plugins: [{
      name: "desktop-video-identity",
      /** Identify the proxy destination before Vite's HTML fallback. */
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url === "/__chattft_video__/identity") {
            response.setHeader("content-type", "application/json");
            response.setHeader("cache-control", "no-store");
            response.end(JSON.stringify({ app: values.wisps ? "wisps" : "vod", backendPort }));
          } else if (request.url === "/__chattft_desktop__/identity" && process.env.CHATTFT_DESKTOP_IDENTITY) {
            response.setHeader("x-chattft-desktop-identity", process.env.CHATTFT_DESKTOP_IDENTITY);
            response.end();
          } else next();
        });
      },
    }],
    server: {
      host: "127.0.0.1", port, strictPort: true,
      proxy: { "/api": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: true } },
    },
  });
  try {
    await server.listen();
  } catch (error) {
    await server.close();
    throw error;
  }
  server.printUrls();
  if (values.managed) emitEvent("listening", { port });
  return server;
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  startVodFrontend().catch((error) => {
    console.error(`Could not start VOD frontend: ${error.message}`);
    process.exitCode = 1;
  });
}
