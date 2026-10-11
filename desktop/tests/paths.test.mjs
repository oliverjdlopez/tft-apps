/** Verify suite paths and migrated launcher isolation without starting live apps. */
import assert from "node:assert/strict";
import path from "node:path";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { launcherPaths } from "../paths.mjs";
import { launchOptions, ensureLangfuse, wslCommand, serviceEnvironment } from "../utils.mjs";
import { VideoRuntime } from "../video-runtime.mjs";

test("launch from another directory uses the suite's independent interpreters", () => {
  const roots = launcherPaths("/tmp/suite with spaces");
  assert.equal(roots.chat, "/tmp/suite with spaces/tft-chat");
  assert.equal(roots.vod, "/tmp/suite with spaces/vod-review");
  assert.equal(launchOptions([], roots.suite).python, `${roots.chat}/.venv/bin/python`);
  const runtime = new VideoRuntime(roots.suite, process.execPath, {});
  assert.equal(runtime.repo, roots.vod);
  assert.equal(runtime.python, `${roots.vod}/.venv/bin/python`);
  assert.equal(runtime.cwd, roots.vod);
});

test("WSL paths remain Linux paths when the native shell runs on Windows", () => {
  const suite = "/home/dev/tft-apps";
  const wsl = { root: suite, node: "/usr/bin/node", distro: "Ubuntu", user: "dev", env: { HOME: "/home/dev" } };
  const runtime = new VideoRuntime(suite, wsl.node, {}, wsl);
  assert.equal(runtime.python, `${suite}/vod-review/.venv/bin/python`);
  assert.equal(runtime.roots.desktop, `${suite}/desktop`);
  assert.equal(wslCommand(wsl).args.at(-1), `${suite}/desktop/wsl-worker.mjs`);
  assert.equal(launcherPaths("C:\\suite", path.win32).chat, "C:\\suite\\tft-chat");
});

test("supporting services have suite-specific projects, volumes, and host ports", async () => {
  const cloud = await readFile(new URL("../cloudbeaver/compose.yaml", import.meta.url), "utf8");
  const evals = await readFile(new URL("../../tft-chat/evals/langfuse/compose.yaml", import.meta.url), "utf8");
  assert.match(cloud, /name: tft-apps-cloudbeaver/);
  assert.match(cloud, /127.0.0.1:8979:8978/);
  assert.match(evals, /name: tft-apps-evals/);
  assert.match(evals, /127.0.0.1:15510:3000/);
  assert.doesNotMatch(evals, /external: true|name: chattft-evals/);
  await ensureLangfuse("/tmp/suite", "/python", {
    request: async (url) => { assert.equal(url, "http://127.0.0.1:15510/api/public/health"); return { ok: true }; },
    runnerReady: async () => true, log() {},
    spawnProcess: () => assert.fail("Ready destination service should be reused"),
  });
});

test("inherited original runtime paths and tracing keys cannot escape the destination", () => {
  const roots = launcherPaths("/tmp/suite");
  const original = { RDS_HOST: "external.example", VOD_DATA_DIR: "/original/data",
    VOD_GDRIVE_CLIENT_FILE: "/external/oauth.json", VOD_GDRIVE_TOKEN_FILE: "/original/token.json",
    LANGFUSE_PUBLIC_KEY: "original-key", LANGFUSE_BASE_URL: "http://localhost:15500",
    TFT_MEDIA_DIR: "/original/catalog" };
  const env = serviceEnvironment(original, roots, roots.vod);
  assert.equal(env.RDS_HOST, original.RDS_HOST);
  assert.equal(env.VOD_GDRIVE_CLIENT_FILE, original.VOD_GDRIVE_CLIENT_FILE);
  assert.equal(env.VOD_DATA_DIR, "/tmp/suite/vod-review/data");
  assert.equal(env.VOD_GDRIVE_TOKEN_FILE, "/tmp/suite/vod-review/data/gdrive/token.json");
  assert.equal(env.TFT_MEDIA_DIR, "/tmp/suite/media");
  assert.equal(serviceEnvironment(original, roots, roots.chat).TFT_MEDIA_DIR, env.TFT_MEDIA_DIR);
  assert.equal(serviceEnvironment({}, roots, roots.vod).TFT_MEDIA_DIR, env.TFT_MEDIA_DIR);
  assert.equal(env.LANGFUSE_BASE_URL, "http://localhost:15510");
  assert.equal(env.LANGFUSE_PUBLIC_KEY, undefined);
  assert.equal(original.VOD_DATA_DIR, "/original/data");
});
