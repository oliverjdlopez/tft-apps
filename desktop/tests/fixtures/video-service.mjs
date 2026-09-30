/** Isolated video-service process for ownership and readiness regression tests. */
import http from "node:http";
import { createInterface } from "node:readline";
const [kind, port] = process.argv.slice(2);
const server = http.createServer((request, response) => {
  response.setHeader("content-type", "application/json");
  response.end(JSON.stringify(kind === "backend" && request.url === "/openapi.json"
    ? { info: { title: "Framewise Video Analysis and Annotation" }, paths: {
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
