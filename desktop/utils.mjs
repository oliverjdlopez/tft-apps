/** Shared desktop launch, process ownership, and navigation helpers. */
import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import path from "node:path";
import { createInterface } from "node:readline";
import { setTimeout as delay } from "node:timers/promises";
import { parseArgs } from "node:util";
import { createHash, randomUUID } from "node:crypto";
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import net from "node:net";
import http from "node:http";
import { tmpdir } from "node:os";

export const EVENT_PREFIX = "CHAT_TFT_DESKTOP ";

// ---------------------------------------------------------------------------
//
// Launch configuration helpers
// Resolve native executables without invoking a shell or modifying the checkout.
//
// ---------------------------------------------------------------------------

/**
 * Resolve a native checkout interpreter or an explicit executable override.
 * Args:
 *   root: Checkout root; override: optional executable; platform: host platform;
 *   cwd: directory against which explicit relative paths are resolved.
 * Returns:
 *   A path or a bare executable name for direct spawning.
 */
export function pythonExecutable(root, override, platform = process.platform, cwd = process.cwd()) {
  const paths = platform === "win32" ? path.win32 : path.posix;
  if (!override) return paths.join(root, ".venv", platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return paths.isAbsolute(override) || !/[\\/]/.test(override) ? override : paths.resolve(cwd, override);
}

/**
 * Validate launch options before starting any service.
 * Args:
 *   args: User command-line arguments; root: checkout root.
 * Returns:
 *   Resolved mode, interpreter, ports, timeout, and help flag.
 */
export function launchOptions(args, root) {
  const { values } = parseArgs({ args, allowPositionals: false, options: {
    mode: { type: "string", default: "production" },
    python: { type: "string" }, port: { type: "string" },
    "dev-port": { type: "string", default: "5173" },
    "startup-timeout": { type: "string", default: "120" },
    help: { type: "boolean", default: false },
  } });
  if (!["production", "dev"].includes(values.mode)) throw new Error("--mode must be production or dev.");
  const port = values.port === undefined ? undefined : integerOption(values.port, "--port", 65535);
  const devPort = integerOption(values["dev-port"], "--dev-port", 65535);
  return {
    mode: values.mode, python: pythonExecutable(root, values.python), port, devPort,
    startupTimeout: integerOption(values["startup-timeout"], "--startup-timeout", 3600) * 1000,
    help: values.help,
  };
}

/**
 * Reject malformed numeric options instead of silently choosing another port.
 * Args:
 *   value: Raw option; name: display name; maximum: inclusive upper bound.
 * Returns:
 *   Validated positive integer.
 */
export function integerOption(value, name, maximum) {
  if (!/^\d+$/.test(value) || Number(value) < 1 || Number(value) > maximum) {
    throw new Error(`${name} must be an integer between 1 and ${maximum}.`);
  }
  return Number(value);
}

/**
 * Start an unavailable Langfuse workspace before launching the desktop shell.
 * Args:
 *   root: Checkout root; python: selected checkout interpreter;
 *   dependencies: Optional HTTP/process/log adapters for isolated launch tests.
 * Returns:
 *   Whether Langfuse was already healthy or its launcher completed successfully.
 */
export async function ensureLangfuse(root, python, {
  request = fetch, spawnProcess = spawn, log = console.log, warn = console.warn,
  runnerReady = hostExperimentReady,
} = {}) {
  try {
    const response = await request("http://127.0.0.1:15500/api/public/health", {
      redirect: "manual", signal: AbortSignal.timeout(1500),
    });
    await response.body?.cancel();
    if (response.ok && await runnerReady(root)) {
      log("[Langfuse] Already running at http://localhost:15500");
      return true;
    }
  } catch { /* A stopped stack is the normal reason to invoke the launcher. */ }

  log("[Langfuse] Starting Docker services; first startup can take several minutes...");
  try {
    // Reuse credential creation, migration checks, and seeding from the official
    // repository launcher rather than bringing up an incomplete Compose stack.
    await new Promise((resolve, reject) => {
      const child = spawnProcess(python, ["-m", "evals", "up", "--no-browser"], {
        cwd: root, shell: false, stdio: "inherit", timeout: 900000,
      });
      child.once("error", reject);
      child.once("close", (code, signal) => {
        if (code === 0) resolve();
        else reject(new Error(`launcher exited with ${signal ?? code}`));
      });
    });
    return true;
  } catch (error) {
    warn(`[Langfuse] Could not start: ${error.message}. Ensure Docker is running, then run uv run --extra evals chat-tft-evals up --no-browser and retry the Langfuse tab. Continuing ChatTFT startup.`);
    return false;
  }
}

/** Check the host evaluation queue over its private socket before desktop reuse. */
export function hostExperimentReady(root) {
  return new Promise((resolve) => {
    const request = http.get({ socketPath: path.join(root, "evals/langfuse/.runtime/runner.sock"), path: "/health" }, (response) => {
      response.resume();
      resolve(response.statusCode === 200);
    });
    request.setTimeout(1500, () => request.destroy());
    request.on("error", () => resolve(false));
    request.on("close", () => resolve(false));
  });
}

// ---------------------------------------------------------------------------
//
// Runtime process helpers
// Structured lifecycle events are kept separate from ordinary service logs.
//
// ---------------------------------------------------------------------------

/**
 * Spawn one directly owned process, capturing lifecycle events and completion.
 * Args:
 *   command: Native executable; args: argument array; options: cwd, label,
 *   optional environment and completion callback.
 * Returns:
 *   Process handle with a non-rejecting completion promise and event history.
 */
export function ownedProcess(command, args, { cwd, label, env = process.env, onExit = () => {} }) {
  const child = spawn(command, args, { cwd, env, windowsHide: true, shell: false, stdio: ["pipe", "pipe", "pipe"] });
  const events = new EventEmitter();
  const records = new Map();
  const handle = { child, events, records, label, ended: false, stopping: false };
  // EPIPE is normal when the child exits between the shutdown request and write.
  child.stdin.on("error", () => {});
  const lines = createInterface({ input: child.stdout });
  lines.on("line", (line) => {
    if (line.startsWith(EVENT_PREFIX)) {
      try {
        const record = JSON.parse(line.slice(EVENT_PREFIX.length));
        records.set(record.type, record);
        events.emit("record", record);
        return;
      } catch { /* A malformed event remains ordinary terminal output. */ }
    }
    console.log(`[${label}] ${line}`);
  });
  child.stderr.on("data", (data) => process.stderr.write(data));
  handle.finished = new Promise((resolve) => {
    const finish = (result) => {
      if (handle.ended) return;
      handle.ended = true;
      handle.result = result;
      resolve(result);
      onExit(handle);
    };
    child.once("error", (error) => finish({ error }));
    child.once("close", (code, signal) => finish({ code, signal }));
  });
  return handle;
}

/**
 * Turn process failures into actionable text without forwarding arbitrary logs.
 * Args:
 *   handle: Owned process that failed or exited unexpectedly.
 * Returns:
 *   Error appropriate for the desktop status dialog.
 */
export function processFailure(handle) {
  const message = handle.records.get("error")?.message;
  if (message) return new Error(message);
  if (handle.result?.error?.code === "ENOENT") {
    return new Error(`${handle.label} executable was not found. Install the checkout dependencies; use --python for a custom Python environment.`);
  }
  return new Error(`${handle.label} exited unexpectedly. Check the launch terminal for details, then retry.`);
}

/**
 * Await one ownership event while also detecting child exit or cancellation.
 * Args:
 *   handle: Owned process; type: event name; signal: startup cancellation.
 * Returns:
 *   Matching lifecycle event.
 */
export async function waitForRecord(handle, type, signal) {
  signal.throwIfAborted();
  if (handle.records.has(type)) return handle.records.get(type);
  let listener;
  try {
    return await abortable(Promise.race([
      new Promise((resolve) => {
        listener = (record) => { if (record.type === type) resolve(record); };
        handle.events.on("record", listener);
      }),
      handle.finished.then(() => { throw processFailure(handle); }),
    ]), signal);
  } finally {
    handle.events.off("record", listener);
  }
}

/**
 * Cancel waiting without leaving abort listeners attached after success.
 * Args:
 *   promise: Operation to await; signal: lifetime controlling the operation.
 * Returns:
 *   The operation's result, or rejection with the cancellation reason.
 */
export async function abortable(promise, signal) {
  signal.throwIfAborted();
  let listener;
  try {
    return await Promise.race([promise, new Promise((_, reject) => {
      listener = () => reject(signal.reason);
      signal.addEventListener("abort", listener, { once: true });
    })]);
  } finally {
    signal.removeEventListener("abort", listener);
  }
}

/**
 * Wait for successful HTTP readiness without following a different server URL.
 * Args:
 *   url: Owned service URL; signal: startup timeout/cancellation signal.
 * Returns:
 *   Nothing once the endpoint returns HTTP 200.
 */
export async function waitForHttp(url, signal) {
  while (true) {
    signal.throwIfAborted();
    try {
      const response = await fetch(url, {
        redirect: "manual", signal: AbortSignal.any([signal, AbortSignal.timeout(1500)]),
      });
      await response.body?.cancel();
      if (response.status === 200) return;
    } catch { signal.throwIfAborted(); }
    await delay(150, undefined, { signal });
  }
}

/**
 * Stop only an owned child, allowing its pipe-based graceful shutdown first.
 * Args:
 *   handle: Owned process; graceMs: maximum time before forced termination.
 * Returns:
 *   Completion after exit, rejecting if the OS cannot terminate the child.
 */
export async function stopProcess(handle, graceMs = 12000) {
  handle.stopping = true;
  if (handle.ended) return;
  handle.child.stdin.end("shutdown\n");
  let timer;
  try {
    await Promise.race([handle.finished, new Promise((resolve) => { timer = setTimeout(resolve, graceMs); })]);
  } finally { clearTimeout(timer); }
  if (handle.ended) return;
  handle.child.kill("SIGKILL");
  await abortable(handle.finished, AbortSignal.timeout(3000));
}

// ---------------------------------------------------------------------------
//
// Window navigation helpers
// Only explicit HTTP(S) destinations can leave the application for a browser.
//
// ---------------------------------------------------------------------------

/**
 * Classify a destination before loading it or passing it to the operating system.
 * Args:
 *   target: Requested URL; appOrigin: currently owned frontend origin.
 * Returns:
 *   internal, external, or blocked.
 */
export function navigationPolicy(target, appOrigin) {
  try {
    const url = new URL(target);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) return "blocked";
    return url.origin === appOrigin ? "internal" : "external";
  } catch { return "blocked"; }
}

/**
 * Limit permission grants to clipboard writes from the owned frontend.
 * Args:
 *   permission: Chromium permission name; requestingUrl: requesting frame URL;
 *   appOrigin: owned frontend origin; mainFrame: whether this is the top frame.
 * Returns:
 *   Whether the request belongs to the existing UI's copy action.
 */
export function permissionAllowed(permission, requestingUrl, appOrigin, mainFrame = true) {
  return mainFrame && permission === "clipboard-sanitized-write"
    && navigationPolicy(requestingUrl, appOrigin) === "internal";
}

// ---------------------------------------------------------------------------
//
// Frontend worker helpers
// Native Node is retained for Vite rather than using Electron as a Node runtime.
//
// ---------------------------------------------------------------------------

/**
 * Report a non-secret frontend lifecycle event to Electron.
 * Args:
 *   type: Lifecycle event; fields: explicitly selected metadata.
 */
export function emitEvent(type, fields = {}) {
  process.stdout.write(`${EVENT_PREFIX}${JSON.stringify({ type, ...fields })}\n`);
}

/**
 * Observe loss of a parent-owned pipe, including abrupt parent termination.
 * Args:
 *   shutdown: Async cleanup operation to run once on command or EOF.
 */
export function watchParent(shutdown) {
  let stopping = false;
  const stop = () => {
    if (stopping) return;
    stopping = true;
    const deadline = setTimeout(() => process.exit(1), 10000);
    Promise.resolve().then(shutdown).then(
      () => { clearTimeout(deadline); process.exit(0); },
      () => process.exit(1),
    );
  };
  const lines = createInterface({ input: process.stdin });
  lines.on("line", (line) => { if (line.trim() === "shutdown") stop(); });
  lines.on("close", stop);
}

// ---------------------------------------------------------------------------
//
// WSL bridge helpers
// Preserve Linux paths and process ownership while the shell runs on Windows.
//
// ---------------------------------------------------------------------------

/**
 * Extract bridge-only flags before validating ordinary application options.
 * Args:
 *   args: Arguments from the WSL terminal.
 * Returns:
 *   Setup flag, Windows executable override, and remaining application args.
 */
export function splitWslOptions(args) {
  const result = { setup: false, applicationArgs: [] };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--setup-windows") result.setup = true;
    else if (arg === "--windows-node" || arg.startsWith("--windows-node=")) {
      const value = arg.includes("=") ? arg.slice(arg.indexOf("=") + 1) : args[++index];
      if (!value || value.startsWith("--") || !path.posix.isAbsolute(value)) {
        throw new Error("--windows-node requires a WSL path such as /mnt/c/Program Files/nodejs/node.exe.");
      }
      result.windowsNode = value;
    } else result.applicationArgs.push(arg);
  }
  return result;
}

/**
 * Build a direct WSL invocation without shell quoting or default-distro guesses.
 * Args:
 *   context: Original Linux distribution, user, checkout, and Node executable.
 * Returns:
 *   Windows executable and literal arguments; Linux cwd is set by WSL itself.
 */
export function wslCommand(context) {
  return {
    command: "wsl.exe",
    args: ["--distribution", context.distro, "--user", context.user, "--cd", context.root,
      "--exec", context.node, path.posix.join(context.root, "desktop/wsl-worker.mjs")],
  };
}

/**
 * Require the owned service's unpredictable identity before loading localhost.
 * Args:
 *   origin: Windows-visible loopback origin; identity: random launch identifier;
 *   signal: Startup deadline/cancellation.
 * Returns:
 *   Nothing on success; rejects wrong servers and unavailable WSL forwarding.
 */
export async function waitForIdentity(origin, identity, signal) {
  while (true) {
    signal.throwIfAborted();
    let response;
    try {
      response = await fetch(`${origin}/__chattft_desktop__/identity`, {
        redirect: "manual", signal: AbortSignal.any([signal, AbortSignal.timeout(1500)]),
      });
      const matches = response.status === 200 && response.headers.get("x-chattft-desktop-identity") === identity;
      await response.body?.cancel();
      if (matches) return;
    } catch {
      if (signal.aborted) throw new Error("WSL localhost startup was cancelled or timed out. Check Windows-to-WSL localhost forwarding and port conflicts; see docs/apps/desktop.md.");
    }
    if (response) throw new Error(`Port ${new URL(origin).port} reaches a different server on Windows. Stop the conflicting server or choose another --port / --dev-port.`);
    await delay(150, undefined, { signal });
  }
}

/**
 * Locate an installed Windows Electron binary without triggering a download.
 * Args:
 *   cache: Windows runtime package directory, separate from Linux dependencies.
 * Returns:
 *   Executable path, or an actionable first-time setup error.
 */
export async function electronExecutable(cache) {
  try {
    const executable = path.join(cache, "node_modules/electron/dist/electron.exe");
    await access(executable);
    return executable;
  } catch { throw new Error("Windows Electron is not installed for this version. Run npm run setup:wsl in desktop/ from WSL, then retry."); }
}

/**
 * Stage only desktop shell sources into an immutable Windows cache directory.
 * Args:
 *   source: Checkout desktop directory; cache: installed Windows runtime directory.
 * Returns:
 *   Shell directory keyed by its content, leaving running launches untouched.
 */
export async function stageWindowsShell(source, cache) {
  const names = ["package.json", "main.mjs", "runtime.mjs", "video-runtime.mjs", "utils.mjs", "status.html", "status.js", "status.css", "workspace.mjs", "workspace-preload.cjs", "workspace.html", "workspace.js", "workspace.css"];
  const files = await Promise.all(names.map(async (name) => [name, await readFile(path.join(source, name))]));
  const hash = createHash("sha256");
  for (const [name, content] of files) hash.update(name).update(content);
  const destination = path.join(cache, "shells", hash.digest("hex").slice(0, 20));
  await mkdir(destination, { recursive: true });
  for (const [name, content] of files) {
    try { await writeFile(path.join(destination, name), content, { flag: "wx" }); }
    catch (error) { if (error.code !== "EEXIST") throw error; }
  }
  return destination;
}

/**
 * Own a private local pipe for Windows GUI Electron, whose stdin can be closed.
 * Returns:
 *   Pipe name, graceful shutdown sender, and final resource cleanup operation.
 */
export async function createParentPipe() {
  const name = process.platform === "win32"
    ? `\\\\.\\pipe\\chattft-desktop-${randomUUID()}`
    : path.join(tmpdir(), `chattft-desktop-${randomUUID()}.sock`);
  const sockets = new Set();
  let stopping = false;
  const server = net.createServer((socket) => {
    sockets.add(socket);
    socket.on("error", () => {});
    socket.on("close", () => sockets.delete(socket));
    if (stopping) socket.end("shutdown\n");
  });
  server.maxConnections = 1;
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(name, resolve);
  });
  return {
    name,
    /** Forward Quit to the connected shell, or remember it for a late connection. */
    shutdown() { stopping = true; for (const socket of sockets) socket.end("shutdown\n"); },
    /** Close the bootstrap endpoint so the shell also observes parent loss. */
    close() { for (const socket of sockets) socket.destroy(); server.close(); },
  };
}

// ---------------------------------------------------------------------------
//
// Workspace helpers
// Authenticate shell commands independently of the hosted applications.
//
// ---------------------------------------------------------------------------

/**
 * Accept fixed commands only from the local shell's top-level frame.
 * Args:
 *   event: IPC event; contents: shell WebContents; shellUrl: trusted file URL;
 *   action: requested workspace action.
 * Returns:
 *   Whether the shell is authorized to dispatch this command.
 */
export function workspaceCommandAllowed(event, contents, shellUrl, action) {
  return event.sender === contents && event.senderFrame === contents.mainFrame
    && event.senderFrame?.url === shellUrl && ["chat", "rolldown", "flowchart", "compositions", "vod", "wisps", "langfuse", "database", "retry"].includes(action);
}

// ---------------------------------------------------------------------------
//
// Video runtime helpers
// Identify compatible services without adopting their process lifetime.
//
// ---------------------------------------------------------------------------

/**
 * Recognize a video API or the proxy frontend; reject occupied unrelated ports.
 * Args:
 *   origin: Fixed loopback URL; kind: backend or frontend; tab: vod or wisps;
 *   signal: Startup cancellation signal.
 * Returns:
 *   True for a compatible service, false only for a refused connection.
 */
export async function probeVideoService(origin, kind, tab, signal) {
  const endpoint = kind === "backend" ? "/openapi.json" : "/__chattft_video__/identity";
  let response;
  try {
    response = await fetch(`${origin}${endpoint}`, {
      signal: AbortSignal.any([signal, AbortSignal.timeout(3000)]), redirect: "error",
    });
  } catch (error) {
    signal.throwIfAborted();
    if (error.cause?.code === "ECONNREFUSED") return false;
    throw new Error(`Cannot verify ${tab} ${kind} at ${origin}. Check the service and port.`);
  }
  try {
    const data = await response.json();
    if (response.ok && kind === "backend" && data.info?.title === "Framewise Video Analysis and Annotation"
      && data.paths?.["/api/health"]?.get && data.paths?.["/api/videos"]?.get
      && (tab !== "wisps" || data.paths?.["/api/videos/{video_id}/wisps"]?.get)) return true;
    if (response.ok && kind === "frontend" && data.app === tab
      && data.backendPort === (tab === "wisps" ? 8001 : 8000)) return true;
  } catch { /* A non-JSON response is an occupied, incompatible service. */ }
  throw new Error(`Port at ${origin} is not a compatible ${tab} ${kind}. For an older frontend, stop it and retry with the updated desktop launcher.`);
}
