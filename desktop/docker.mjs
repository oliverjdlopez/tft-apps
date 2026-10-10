/** Build and configure suite containers without a host Python environment. */
import { spawn } from "node:child_process";
import { randomBytes, randomUUID, createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, writeFile, rm, readlink, lstat } from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { parseEnv } from "node:util";
import { setTimeout as delay } from "node:timers/promises";

export const SUITE_ROOT = fileURLToPath(new URL("../", import.meta.url));
const IMAGE_ROOT = "/opt/tft-apps";
const FORWARDED = /^(RDS_|AWS_|OPENAI_|ANTHROPIC_|RIOT_|CHAT_TFT_|VOD_|HF_|HUGGING_FACE_|TRANSFORMERS_|OLLAMA_|SSL_CERT_FILE$|REQUESTS_CA_BUNDLE$)/;

/** Read optional dotenv settings privately, preserving parsed literal values. */
export async function readEnvironment(filename) {
  try { return parseEnv(await readFile(filename, "utf8")); }
  catch (error) { if (error.code === "ENOENT") return {}; throw error; }
}

/** Run literal command arguments, never printing configuration or credentials. */
export function run(command, args, { cwd = SUITE_ROOT, env = process.env, capture = false, signal, timeout, trim = true } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, { cwd, env, shell: false, signal,
      stdio: ["ignore", capture ? "pipe" : "inherit", "inherit"], timeout });
    let output = "";
    let failure;
    child.stdout?.on("data", (chunk) => { output += chunk; });
    child.on("error", (error) => { failure = error; });
    child.on("close", (code, stopped) => {
      if (failure) reject(failure);
      else if (code !== 0) reject(new Error(`${command} failed (${stopped ?? code}). Check the service logs.`));
      else resolve(trim ? output.trim() : output);
    });
  });
}

/** Map a host directory into a container, rejecting implicit Docker mkdirs. */
export function bind(source, target = source, readOnly = false) {
  return { type: "bind", source, target, read_only: readOnly, bind: { create_host_path: false } };
}

/** Create suite-owned storage before Docker starts, retaining host ownership. */
async function directory(location) {
  await mkdir(location, { recursive: true });
  return location;
}

/** Forward configured credentials through selected mounts, never image layers. */
export function credentialMounts(environment, home = os.homedir()) {
  const mounts = [];
  const aws = path.join(home, ".aws");
  if (existsSync(aws)) mounts.push(bind(aws, "/home/app/.aws", true));
  for (const name of ["AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE", "AWS_WEB_IDENTITY_TOKEN_FILE", "VOD_GDRIVE_CLIENT_FILE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "AWS_CA_BUNDLE"]) {
    const location = environment[name];
    if (!location) continue;
    if (!path.isAbsolute(location) || !existsSync(location)) throw new Error(`${name} must reference an existing absolute host path.`);
    if (!mounts.some((mount) => mount.target === location)) mounts.push(bind(location, location, true));
  }
  return mounts;
}

/** Select suite-local VOD storage, preventing reuse of an original checkout. */
export function vodDataDirectory(root, environment) {
  const fallback = path.join(root, "vod-review/data");
  if (!environment.VOD_DATA_DIR) return fallback;
  const requested = path.resolve(environment.VOD_DATA_DIR);
  const relative = path.relative(root, requested);
  return relative && relative !== ".." && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative) ? requested : fallback;
}

/** Assemble persistent storage and private settings for one Python service. */
export async function applicationSettings(root, service, inherited = process.env) {
  const appName = service === "vod" ? "vod-review" : "tft-chat";
  const app = path.join(root, appName);
  const imageApp = `${IMAGE_ROOT}/${appName}`;
  const local = await readEnvironment(path.join(app, ".env"));
  const source = { ...local, ...inherited };
  const environment = Object.fromEntries(Object.entries({ ...local,
    ...Object.fromEntries(Object.entries(inherited).filter(([key]) => FORWARDED.test(key))),
  }).filter(([, value]) => value !== undefined));
  Object.assign(environment, { HOME: "/home/app", PYTHONDONTWRITEBYTECODE: "1",
    TFT_MEDIA_DIR: path.join(root, "media") });
  const home = await directory(path.join(root, ".runtime/docker", `${service}-home`));
  const media = await directory(environment.TFT_MEDIA_DIR);
  const volumes = [bind(home, "/home/app"), bind(media), ...credentialMounts(source)];
  // Mount selected model caches to reuse local weights without exposing the
  // user's whole home directory or copying large files into an image.
  for (const relative of [".cache/huggingface", ".cache/torch", ".paddlex", ".cache/paddle", ".cache/modelscope"]) {
    const cached = path.join(os.homedir(), relative);
    if (existsSync(cached)) volumes.push(bind(cached, `/home/app/${relative}`));
  }
  if (service === "vod") {
    const data = await directory(vodDataDirectory(root, source));
    Object.assign(environment, { VOD_DATA_DIR: data, VOD_FRAMES_DIR: `${data}/frames`,
      VOD_BOXES_DIR: `${data}/boxes`, VOD_OCR_CACHE_DIR: `${data}/ocr_cache`,
      VOD_GDRIVE_TOKEN_FILE: `${data}/gdrive/token.json` });
    volumes.push(bind(data), bind(await directory(path.join(app, "artifacts")), `${imageApp}/artifacts`));
    if (inherited.TFT_DOCKER_GPU === "0") {
      environment.VOD_WHISPER_DEVICE = "cpu";
      environment.VOD_WHISPER_COMPUTE_TYPE = "int8";
    }
  } else {
    const platform = await readEnvironment(path.join(app, "evals/langfuse/.env"));
    // Application dotenv files may have been copied from another checkout.
    // Deployment coordinates and keys always belong to this suite's platform.
    for (const key of ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_EXPERIMENT_TOKEN", "LANGFUSE_RUNTIME_DIR", "LANGFUSE_SNAPSHOT_DIR", "LANGFUSE_INIT_USER_EMAIL", "LANGFUSE_INIT_USER_PASSWORD"]) delete environment[key];
    for (const key of ["LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"]) if (platform[key]) environment[key] = platform[key];
    Object.assign(environment, { LANGFUSE_BASE_URL: "http://langfuse-web:3000",
      LANGFUSE_PUBLIC_URL: "http://localhost:15510", LANGFUSE_PROJECT_ID: "tft-apps-evals" });
    for (const relative of ["app/static", ".runtime", "data", "profiles", "gameplans", "scripts/transcription/output"]) {
      volumes.push(bind(await directory(path.join(app, relative)), `${imageApp}/${relative}`));
    }
    // The product's specification editor must still save to the real checkout.
    const specs = "app/backend/src/domain/assistant_specs";
    if (existsSync(path.join(app, specs))) volumes.push(bind(path.join(app, specs), `${imageApp}/${specs}`));
    if (existsSync(path.join(app, "chat_tft.ini"))) volumes.push(bind(path.join(app, "chat_tft.ini"), `${imageApp}/chat_tft.ini`, true));
  }
  return { environment, volumes, appName, imageApp };
}

/** Build the Compose model for one desktop-owned application lifetime. */
export async function applicationCompose(root, options, inherited = process.env) {
  const { service, mode = "production", identity, backendPort, frontendPort } = options;
  if (!["chat", "vod"].includes(service) || !["production", "dev"].includes(mode)) throw new Error("Invalid container application or mode.");
  const settings = await applicationSettings(root, service, inherited);
  const internalPort = service === "chat" ? 8300 : 8000;
  const published = backendPort ?? internalPort;
  const frontend = frontendPort ?? (service === "chat" ? 5173 : 5174);
  const environment = { ...settings.environment, CHATTFT_DESKTOP_IDENTITY: identity ?? "" };
  const backend = { image: `tft-apps-${service}:local`, build: { context: root, dockerfile: `docker/Dockerfile.${service}` },
    command: ["python", `${IMAGE_ROOT}/docker/backend.py`, "--service", service],
    init: true, user: `${process.getuid?.() ?? 1000}:${process.getgid?.() ?? 1000}`,
    environment, volumes: settings.volumes, working_dir: settings.imageApp,
    extra_hosts: ["host.docker.internal:host-gateway"],
    ports: [`127.0.0.1:${published}:${internalPort}`],
    labels: { "com.tft-apps.suite": root, "com.tft-apps.identity": identity ?? "build" },
    stop_grace_period: "25s",
    healthcheck: { test: ["CMD", "python", "-c", `import urllib.request; urllib.request.urlopen('http://127.0.0.1:${internalPort}/${service === "chat" ? "api/config" : "api/health"}', timeout=3)`], interval: "2s", timeout: "5s", retries: 45, start_period: "5s" },
  };
  if ((service === "vod" && inherited.TFT_DOCKER_GPU !== "0") || (service === "chat" && inherited.TFT_DOCKER_CHAT_GPU === "1")) backend.gpus = "all";
  if (service === "vod" && mode === "production" && frontend !== published) backend.ports.push(`127.0.0.1:${frontend}:${internalPort}`);
  const services = { [service]: backend };
  if (mode === "dev") {
    // Mount authored modules only: a host .venv/node_modules must never shadow
    // the image's dependency installation or built assets.
    for (const relative of service === "chat" ? ["app/backend", "evals", "gameplans", "agent_configs"] : ["backend", "round_classifier", "text_detection", "config"]) {
      const source = path.join(root, settings.appName, relative);
      if (existsSync(source)) backend.volumes.push(bind(source, `${settings.imageApp}/${relative}`, true));
    }
    const frontendDir = `${settings.appName}/${service === "chat" ? "app/frontend" : "frontend"}`;
    const imageFrontend = `${IMAGE_ROOT}/${frontendDir}`;
    const sourceFrontend = path.join(root, frontendDir);
    const volumes = [];
    for (const relative of ["src", "public", "index.html", service === "chat" ? "vite.config.js" : "vite.config.ts"]) {
      if (existsSync(path.join(sourceFrontend, relative))) volumes.push(bind(path.join(sourceFrontend, relative), `${imageFrontend}/${relative}`, true));
    }
    services[`${service}-frontend`] = { image: `tft-apps-${service}-frontend:local`,
      build: { context: root, dockerfile: "docker/Dockerfile.frontend", args: { FRONTEND_DIR: frontendDir } },
      init: true, user: backend.user, working_dir: imageFrontend,
      command: ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173", "--strictPort"],
      environment: { TFT_API_PROXY_TARGET: `http://${service}:${internalPort}`, VITE_API_BASE: "", CHATTFT_DESKTOP_IDENTITY: identity ?? "" },
      volumes, ports: [`127.0.0.1:${frontend}:5173`], depends_on: { [service]: { condition: "service_healthy" } },
      healthcheck: { test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:5173').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"], interval: "2s", timeout: "3s", retries: 30 },
    };
  }
  const configuration = { services };
  if (service === "chat") {
    if (inherited.TFT_DOCKER_EVAL_NETWORK) {
      backend.networks = ["default", "evaluations"];
      configuration.networks = { default: {}, evaluations: { external: true, name: inherited.TFT_DOCKER_EVAL_NETWORK } };
    } else {
      // The UI port is bound to host loopback and cannot be reached through a
      // Linux bridge gateway. Keep chat independent when the stack is absent.
      backend.environment.LANGFUSE_TRACING_ENABLED = "false";
    }
  }
  return configuration;
}

/** Find the suite's existing Langfuse network without creating or adopting it. */
export async function evaluationNetwork() {
  try {
    const network = JSON.parse(await run("docker", ["network", "inspect", "tft-apps-evals_default", "--format", "{{json .}}"], { capture: true, timeout: 3000 }));
    return network.Labels?.["com.docker.compose.project"] === "tft-apps-evals" ? network.Name : undefined;
  } catch { return undefined; }
}

/** Escape Compose interpolation so literal dollars in secrets and paths survive. */
export function composeLiterals(value) {
  if (typeof value === "string") return value.replaceAll("$", () => "$$");
  if (Array.isArray(value)) return value.map(composeLiterals);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, composeLiterals(entry)]));
  return value;
}

/** Save a private temporary Compose description; callers remove it after use. */
export async function composeFile(root, configuration) {
  const parent = await directory(path.join(root, ".runtime/docker/config"));
  const filename = path.join(parent, `${randomUUID()}.json`);
  await writeFile(filename, JSON.stringify(composeLiterals(configuration)), { mode: 0o600, flag: "wx" });
  return filename;
}

/** Preserve existing Langfuse keys and generate a new deployment only if absent. */
async function preparePlatform(root) {
  const platform = path.join(root, "tft-chat/evals/langfuse");
  await directory(path.join(platform, ".runtime"));
  const filename = path.join(platform, ".env");
  if (!existsSync(filename)) {
    const values = Object.fromEntries(["POSTGRES_PASSWORD", "CLICKHOUSE_PASSWORD", "REDIS_AUTH", "MINIO_ROOT_PASSWORD", "SALT", "NEXTAUTH_SECRET", "ENCRYPTION_KEY", "LANGFUSE_EXPERIMENT_TOKEN", "LANGFUSE_INIT_USER_PASSWORD"].map((key) => [key, randomBytes(32).toString("hex")]));
    Object.assign(values, { LANGFUSE_PUBLIC_KEY: `pk-lf-${randomBytes(16).toString("hex")}`, LANGFUSE_SECRET_KEY: `sk-lf-${randomBytes(32).toString("hex")}`,
      LANGFUSE_INIT_USER_EMAIL: "evals@chattft.local", HOST_UID: String(process.getuid?.() ?? 1000), HOST_GID: String(process.getgid?.() ?? 1000) });
    try { await writeFile(filename, Object.entries(values).map(([key, value]) => `${key}=${value}\n`).join(""), { mode: 0o600, flag: "wx" }); }
    catch (error) { if (error.code !== "EEXIST") throw error; }
  }
  return platform;
}

/** Configure the persistent evaluation stack using the same application mounts. */
export async function evaluationInvocation(root, inherited = process.env) {
  const platform = await preparePlatform(root);
  const settings = await applicationSettings(root, "chat", inherited);
  const local = await readEnvironment(path.join(platform, ".env"));
  const env = { ...inherited, ...local, HOST_UID: String(process.getuid?.() ?? 1000), HOST_GID: String(process.getgid?.() ?? 1000) };
  try {
    env.CHAT_TFT_GIT_REVISION = await run("git", ["rev-parse", "HEAD"], { cwd: root, capture: true });
    const diff = await run("git", ["diff", "HEAD", "--binary"], { cwd: root, capture: true, trim: false });
    const untracked = await run("git", ["ls-files", "--others", "--exclude-standard", "-z"], { cwd: root, capture: true, trim: false });
    const fingerprint = createHash("sha256").update(diff);
    for (const name of untracked.split("\0").filter(Boolean).sort()) {
      const source = path.join(root, name);
      fingerprint.update(`${name}\0`);
      const stat = await lstat(source);
      if (stat.isSymbolicLink()) fingerprint.update(createHash("sha256").update(await readlink(source)).digest());
      else if (stat.isFile()) fingerprint.update(createHash("sha256").update(await readFile(source)).digest());
    }
    env.CHAT_TFT_WORKING_TREE_FINGERPRINT = fingerprint.digest("hex");
  } catch { env.CHAT_TFT_GIT_REVISION = "unknown"; env.CHAT_TFT_WORKING_TREE_FINGERPRINT = "unknown"; }
  const runnerEnvironment = Object.fromEntries(Object.entries(settings.environment).filter(([key]) => !key.startsWith("LANGFUSE_")));
  const configuration = { services: { experiments: { environment: { ...runnerEnvironment,
    LANGFUSE_BASE_URL: "http://langfuse-web:3000", LANGFUSE_PUBLIC_URL: "http://localhost:15510" },
    volumes: settings.volumes, extra_hosts: ["host.docker.internal:host-gateway"] } } };
  // Test-specific DB/model settings must be applied last so real credentials
  // can never replace an explicitly isolated test deployment's coordinates.
  const filename = await composeFile(root, configuration);
  const args = ["compose", "--project-name", "tft-apps-evals", "--project-directory", platform,
    "--env-file", path.join(platform, ".env"), "-f", path.join(platform, "compose.yaml"), "-f", filename];
  if (inherited.LANGFUSE_TEST_DEPLOYMENT === "1") {
    env.LANGFUSE_LLM_CONNECTION_WHITELISTED_HOST = "mock-model";
    args.push("-f", path.join(platform, "compose.test.yaml"));
  }
  return { args, env, filename, platform };
}

/** Run one evaluation Compose operation and remove its private description. */
export async function evaluationCompose(root, arguments_, options = {}) {
  const invocation = await evaluationInvocation(root, options.env ?? process.env);
  try { return await run("docker", [...invocation.args, ...arguments_], { ...options, env: invocation.env }); }
  finally { await rm(invocation.filename, { force: true }); }
}

/** Refuse to stop or replace a runner with accepted work still pending. */
async function requireIdle(root) {
  const result = await evaluationCompose(root, ["run", "--rm", "--no-deps", "--pull", "never", "-T", "experiments", "python", "-m", "evals", "runner-status"], { capture: true });
  const status = JSON.parse(result);
  if (status.pending) throw new Error("Evaluation jobs are still active. Finish them before migrating or restarting the runner.");
}

/** Retire only a legacy host runner proven to own this suite's exact socket. */
export async function retireHostRunner(root, { checkOnly = false } = {}) {
  const runtime = path.join(root, "tft-chat/evals/langfuse/.runtime");
  const receipt = path.join(runtime, "runner.pid");
  if (!existsSync(receipt)) {
    if (await legacySocketAlive(path.join(runtime, "runner.sock"))) {
      throw new Error("The legacy host runner is reachable without an ownership receipt; no process was stopped.");
    }
    return;
  }
  const pid = Number((await readFile(receipt, "utf8")).trim());
  const commandPath = `/proc/${pid}/cmdline`;
  let command;
  try { command = (await readFile(commandPath)).toString().split("\0"); }
  catch (error) { if (error.code !== "ENOENT") throw error; }
  if (!command && await legacySocketAlive(path.join(runtime, "runner.sock"))) {
    throw new Error("The legacy host runner is reachable but its process ownership is hidden. Run migration directly in the owning WSL session; no process was stopped.");
  }
  if (command) {
    if (!Number.isInteger(pid) || pid <= 1 || !command.includes("evals.langfuse.server:app") || !command.includes(path.join(runtime, "runner.sock"))) {
      throw new Error("Legacy runner ownership could not be verified; no host process was stopped.");
    }
    if (checkOnly) return;
    process.kill(pid, "SIGTERM");
    for (let attempt = 0; attempt < 100 && existsSync(commandPath); attempt++) await delay(100);
    if (existsSync(commandPath)) throw new Error("Legacy runner did not stop; inspect its log before retrying.");
  }
  if (checkOnly) return;
  await rm(receipt, { force: true });
  await rm(path.join(runtime, "runner.sock"), { force: true });
}

/** Detect a host outside our PID namespace before declaring its receipt stale. */
export function legacySocketAlive(socketPath) {
  return new Promise((resolve) => {
    const request = http.get({ socketPath, path: "/health" }, (response) => { response.resume(); resolve(true); });
    request.setTimeout(1500, () => request.destroy());
    request.on("error", () => resolve(false));
  });
}

/** Bring up the existing platform and its container runner without model calls. */
export async function startEvaluations(root = SUITE_ROOT) {
  return withEvaluationLock(root, () => startEvaluationServices(root));
}

/** Serialize queue ownership changes across concurrent desktop launches. */
export async function withEvaluationLock(root, operation) {
  const runtime = await directory(path.join(root, "tft-chat/evals/langfuse/.runtime"));
  const lock = path.join(runtime, "docker-lifecycle.lock");
  try { await mkdir(lock); }
  catch (error) {
    if (error.code === "EEXIST") throw new Error(`Another evaluation lifecycle operation owns ${lock}. If its launcher crashed, verify it has stopped before removing that lock directory.`);
    throw error;
  }
  try {
    await writeFile(path.join(lock, "owner.json"), JSON.stringify({ pid: process.pid, started: new Date().toISOString() }), { mode: 0o600 });
    return await operation();
  } finally { await rm(lock, { recursive: true, force: true }); }
}

/** Perform the handover while holding the suite's lifecycle lock. */
async function startEvaluationServices(root) {
  await run("docker", ["info", "--format", "{{.ServerVersion}}"]);
  await requireIdle(root);
  await retireHostRunner(root, { checkOnly: true });
  // Stop ingress before retiring the host so a new webhook cannot enqueue work
  // between the idle check and the ownership handover.
  await evaluationCompose(root, ["stop", "experiments"]);
  try {
    await requireIdle(root);
    await retireHostRunner(root);
  } catch (error) {
    // Restore the previously running ingress after a refused handover. start
    // never recreates it with the new image or creates a second queue consumer.
    await evaluationCompose(root, ["start", "experiments"]).catch(() => {});
    throw error;
  }
  await evaluationCompose(root, ["up", "-d", "--wait", "--wait-timeout", "600", "langfuse-web", "langfuse-worker"]);
  await evaluationCompose(root, ["run", "--rm", "--no-deps", "--pull", "never", "-T", "experiments", "python", "-m", "evals.langfuse.seed"]);
  await evaluationCompose(root, ["up", "-d", "--no-build", "--wait", "--wait-timeout", "120", "experiments"]);
}

/** Build all app and development images without starting application services. */
export async function buildImages(root = SUITE_ROOT) {
  const services = {};
  for (const service of ["chat", "vod"]) Object.assign(services, (await applicationCompose(root, { service, mode: "dev" })).services);
  const filename = await composeFile(root, { services });
  try { await run("docker", ["compose", "--project-name", "tft-apps-build", "-f", filename, "build"]); }
  finally { await rm(filename, { force: true }); }
}

/** Expose setup and evaluation lifecycle commands to the native desktop shell. */
async function main() {
  const [action, ...args] = process.argv.slice(2);
  if (action === "build") await buildImages();
  else if (action === "langfuse-up") await startEvaluations();
  else if (action === "eval-compose") await evaluationCompose(SUITE_ROOT, args);
  else if (["eval-restart", "eval-down"].includes(action)) {
    await withEvaluationLock(SUITE_ROOT, async () => {
      await requireIdle(SUITE_ROOT);
      await retireHostRunner(SUITE_ROOT, { checkOnly: true });
      await evaluationCompose(SUITE_ROOT, ["stop", "experiments"]);
      try { await requireIdle(SUITE_ROOT); await retireHostRunner(SUITE_ROOT); }
      catch (error) { await evaluationCompose(SUITE_ROOT, ["start", "experiments"]).catch(() => {}); throw error; }
      await evaluationCompose(SUITE_ROOT, action === "eval-down" ? ["down"] : ["up", "-d", "--no-build", "--force-recreate", "--wait", "experiments"]);
    });
  } else throw new Error("Use build, langfuse-up, eval-compose, eval-restart or eval-down.");
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  main().catch((error) => { console.error(error.message); process.exitCode = 1; });
}
