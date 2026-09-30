/** Tiny HTTP process used to test desktop ownership without live API/database calls. */
import { existsSync } from "node:fs";
import http from "node:http";
import path from "node:path";

const [mode, ...args] = process.argv.slice(2);
if (mode === "production") process.exit(existsSync(path.join(process.cwd(), "fail-build")) ? 1 : 0);
const requested = mode === "dev" ? Number(args[0]) : Number(args[args.indexOf("--port") + 1] || 0);
const server = http.createServer((_request, response) => response.end("fixture"));
server.on("error", () => process.exit(1));
server.listen(requested, "127.0.0.1", () => {
  console.log(`CHAT_TFT_DESKTOP ${JSON.stringify({ type: mode === "dev" ? "listening" : "bound", port: server.address().port })}`);
});
process.stdin.on("data", () => server.close(() => process.exit(0)));
process.stdin.on("end", () => server.close(() => process.exit(0)));
process.stdin.resume();
