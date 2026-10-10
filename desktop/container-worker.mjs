/** Own one application's Compose project for the native desktop parent's life. */
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { rm } from "node:fs/promises";
import { parseArgs } from "node:util";
import { setTimeout as delay } from "node:timers/promises";
import { applicationCompose, composeFile, evaluationNetwork, run, SUITE_ROOT } from "./docker.mjs";
import { emitEvent, integerOption } from "./utils.mjs";

/** Start, monitor and clean up a unique project without adopting other services. */
async function main() {
  const { values } = parseArgs({ options: { service: { type: "string" }, mode: { type: "string", default: "production" },
    "backend-port": { type: "string" }, "frontend-port": { type: "string" }, identity: { type: "string" } } });
  if (!/^[0-9a-f-]{36}$/.test(values.identity ?? "")) throw new Error("A desktop launch identity is required.");
  const backendPort = integerOption(values["backend-port"], "--backend-port", 65535);
  const frontendPort = integerOption(values["frontend-port"], "--frontend-port", 65535);
  const controller = new AbortController();
  const stop = () => controller.abort();
  const parent = createInterface({ input: process.stdin });
  parent.on("line", (line) => { if (line === "shutdown") stop(); });
  parent.on("close", stop);
  process.on("SIGINT", stop);
  process.on("SIGTERM", stop);
  let filename;
  let compose;
  let logs;
  let started = false;
  try {
    const environment = { ...process.env };
    delete environment.TFT_DOCKER_EVAL_NETWORK;
    if (values.service === "chat") environment.TFT_DOCKER_EVAL_NETWORK = await evaluationNetwork();
    const configuration = await applicationCompose(SUITE_ROOT, { service: values.service, mode: values.mode,
      identity: values.identity, backendPort, frontendPort }, environment);
    controller.signal.throwIfAborted();
    filename = await composeFile(SUITE_ROOT, configuration);
    compose = ["compose", "--project-name", `tft-apps-${values.service}-${values.identity}`, "-f", filename];
    started = true;
    await run("docker", [...compose, "up", "-d", "--no-build", "--pull", "never", "--wait", "--wait-timeout", "100"], { signal: controller.signal });
    controller.signal.throwIfAborted();
    logs = spawn("docker", [...compose, "logs", "--follow", "--no-color", "--tail", "25"], { stdio: ["ignore", "inherit", "inherit"], shell: false });
    logs.on("error", () => {});
    emitEvent("bound", { port: backendPort });
    emitEvent("listening", { port: frontendPort });
    while (!controller.signal.aborted) {
      await delay(2000, undefined, { signal: controller.signal });
      const status = await run("docker", [...compose, "ps", "--all", "--format", "json"], { capture: true, signal: controller.signal });
      const containers = status.startsWith("[") ? JSON.parse(status) : status.split("\n").filter(Boolean).map((line) => JSON.parse(line));
      if (Object.keys(configuration.services).some((service) => !containers.some((container) => container.Service === service && container.State === "running" && container.Health !== "unhealthy"))) {
        throw new Error("An application container stopped or became unhealthy. Check the service logs, then retry.");
      }
    }
  } catch (error) {
    if (!controller.signal.aborted) {
      if (started && !logs) {
        await run("docker", [...compose, "logs", "--no-color", "--tail", "50"], { timeout: 5000 }).catch(() => {});
      }
      emitEvent("error", { message: "Container startup or operation failed. Run the suite setup, check Docker and GPU access, and inspect the terminal logs." });
      console.error(error.message);
      process.exitCode = 1;
    }
  } finally {
    logs?.kill("SIGTERM");
    let cleaned = true;
    if (started) {
      try { await run("docker", [...compose, "down", "--timeout", "25"], { timeout: 35000 }); }
      catch {
        cleaned = false;
        emitEvent("cleanup_error", { message: "Owned containers could not be stopped. Check Docker before retrying the desktop." });
        process.exitCode = 1;
      }
    }
    if (filename && cleaned) await rm(filename, { force: true });
    parent.close();
    process.stdin.destroy();
  }
}

main().catch((error) => { console.error(error.message); process.exitCode = 1; });
