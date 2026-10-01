/** Run an independently installed VOD frontend with a same-origin backend proxy. */
import path from "node:path";
import { launcherPaths } from "./paths.mjs";
import { pathToFileURL } from "node:url";
import { parseArgs } from "node:util";
import { emitEvent, watchParent, integerOption } from "./utils.mjs";

/**
 * Start the selected checkout's Vite server without changing its configuration.
 * Args:
 *   args: CLI arguments; --repo selects an installed VOD application, and
 *     optional --port/--backend-port isolate smoke services.
 * Returns:
 *   The listening Vite server, owned by this foreground command.
 */
export async function startVodFrontend(args = process.argv.slice(2)) {
  const { values } = parseArgs({ args, options: {
    managed: { type: "boolean", default: false },
    repo: { type: "string" },
    port: { type: "string", default: "5174" },
    "backend-port": { type: "string", default: "8000" },
  } });
  const root = path.resolve(values.repo ?? launcherPaths().vod);
  const frontend = path.join(root, "frontend");
  const port = integerOption(values.port, "--port", 65535);
  const backendPort = integerOption(values["backend-port"], "--backend-port", 65535);
  // The existing clients accept an empty base URL. Proxying avoids widening
  // backend CORS rules and keeps video playback and uploads on the same origin.
  process.env.VITE_API_BASE = "";
  const { createServer } = await import(pathToFileURL(path.join(frontend, "node_modules/vite/dist/node/index.js")).href);
  let server;
  if (values.managed) watchParent(async () => { await server?.close(); });
  server = await createServer({
    root: frontend,
    configFile: path.join(frontend, "vite.config.ts"),
    plugins: [{
      name: "desktop-video-identity",
      /** Identify the proxy destination before Vite's HTML fallback. */
      configureServer(vite) {
        vite.middlewares.use((request, response, next) => {
          if (request.url === "/__chattft_desktop__/identity" && process.env.CHATTFT_DESKTOP_IDENTITY) {
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
