/** Isolated video-service process for ownership and readiness regression tests. */
import http from "node:http";
import { createInterface } from "node:readline";
const [kind, port] = process.argv.slice(2);
const server = http.createServer((request, response) => {
  response.setHeader("content-type", "application/json");
  if (request.url === "/__chattft_desktop__/identity") response.setHeader("x-chattft-desktop-identity", process.env.CHATTFT_DESKTOP_IDENTITY);
  response.end(JSON.stringify(kind === "backend" && request.url === "/openapi.json"
    ? { info: { title: "VOD Review and Round Classification" }, paths: {
      "/api/health": { get: {} }, "/api/videos": { get: {} },
    } } : kind === "frontend" ? { app: "vod", backendPort: 8000 } : { status: "ok" }));
});
server.listen(Number(port), "127.0.0.1", () => {
  console.log("CHAT_TFT_DESKTOP " + JSON.stringify({ type: kind === "backend" ? "bound" : "listening", port: Number(port) }));
});
const input = createInterface({ input: process.stdin });
/** Stop only this fixture's HTTP listener after its owning pipe closes. */
function stop() { server.closeAllConnections(); server.close(() => process.exit(0)); }
input.on("line", stop);
input.on("close", stop);
