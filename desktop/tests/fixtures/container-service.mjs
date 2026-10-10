/** Simulate one container guardian with real HTTP ports and parent-pipe cleanup. */
import { existsSync } from "node:fs";
import http from "node:http";
import path from "node:path";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: {
  service: { type: "string" }, mode: { type: "string" },
  "backend-port": { type: "string" }, "frontend-port": { type: "string" },
  identity: { type: "string" },
} });
const servers = [];
let stopped = false;

/** Read a scenario marker from the isolated fixture checkout. */
function marker(name) { return existsSync(path.join(process.cwd(), name)); }

/** Emit the same bounded lifecycle records as the Docker guardian. */
function record(type, fields = {}) {
  console.log("CHAT_TFT_DESKTOP " + JSON.stringify({ type, ...fields }));
}

/** Release both fixture listeners on parent command or EOF. */
async function stop() {
  if (stopped) return;
  stopped = true;
  await Promise.all(servers.map((server) => new Promise((resolve) => {
    server.closeAllConnections();
    server.close(resolve);
  })));
  if (marker("fail-cleanup")) record("cleanup_error", { message: "Fixture cleanup failure" });
  process.exit(marker("fail-cleanup") ? 1 : 0);
}

/** Bind one owned endpoint and expose its per-launch identity. */
function listen(port) {
  return new Promise((resolve, reject) => {
    const server = http.createServer((request, response) => {
      if (request.url === "/__chattft_desktop__/identity") {
        response.setHeader("x-chattft-desktop-identity", marker("wrong-identity") ? "someone-else" : values.identity);
      }
      response.end("fixture");
    });
    servers.push(server);
    server.on("error", reject);
    server.listen(port, "127.0.0.1", () => resolve(server));
  });
}

process.stdin.on("data", stop);
process.stdin.on("end", stop);
process.stdin.resume();

/** Start both service endpoints without Docker or application dependencies. */
async function start() {
  if (marker("stall-container")) return;
  if (marker("fail-container")) throw new Error("Fixture container startup failure");
  const backendPort = Number(values["backend-port"]);
  const frontendPort = Number(values["frontend-port"]);
  await listen(backendPort);
  record("bound", { port: marker("wrong-bound") ? backendPort + 1 : backendPort });
  if (marker("fail-frontend")) throw new Error("Fixture frontend startup failure");
  if (frontendPort !== backendPort) await listen(frontendPort);
  record("listening", { port: marker("wrong-listening") ? frontendPort + 1 : frontendPort });
}

start().catch((error) => {
  record("error", { message: error.message });
  process.exit(1);
});
