/** Run the checkout's Vite build or development server with native Node. */
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";
import { launcherPaths } from "./paths.mjs";
import { emitEvent, watchParent } from "./utils.mjs";

/** Reuse frontend configuration while making desktop service ownership explicit. */
async function main() {
  const [mode, port, backendPort] = process.argv.slice(2);
  const root = path.join(launcherPaths().chat, "app/frontend");
  let server;
  watchParent(async () => { await server?.close(); });
  const require = createRequire(path.join(root, "package.json"));
  let vite;
  try { vite = await import(pathToFileURL(require.resolve("vite")).href); } catch {
    emitEvent("error", { message: "Frontend dependencies are unavailable. Run npm ci in app/frontend, then retry." });
    process.exit(1);
  }
  const configFile = path.join(root, "vite.config.js");
  if (mode === "production") {
    await vite.build({ root, configFile });
    process.exit(0);
  }
  const target = `http://127.0.0.1:${backendPort}`;
  server = await vite.createServer({ root, configFile, server: {
    host: "127.0.0.1", port: Number(port), strictPort: true, open: false,
    proxy: { "/api": target, "/static": target },
  }, plugins: [{
    name: "desktop-service-identity",
    /** Expose the owning Vite process identity before existing middleware runs. */
    configureServer(server) {
      const identity = process.env.CHATTFT_DESKTOP_IDENTITY;
      if (!identity) return;
      server.middlewares.use((request, response, next) => {
        if (request.url !== "/__chattft_desktop__/identity") return next();
        response.setHeader("x-chattft-desktop-identity", identity);
        response.setHeader("cache-control", "no-store");
        response.end();
      });
    },
  }] });
  await server.listen();
  emitEvent("listening", { port: Number(port) });
}

main().catch((error) => {
  console.error(error);
  emitEvent("error", { message: "Frontend build or startup failed. Check the launch terminal; for a busy Vite port, use --dev-port." });
  process.exit(1);
});
