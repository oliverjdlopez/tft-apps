/** Verify container storage, credential boundaries and lifecycle concurrency. */
import assert from "node:assert/strict";
import test from "node:test";
import os from "node:os";
import path from "node:path";
import http from "node:http";
import { once } from "node:events";
import { mkdtemp, mkdir, writeFile, readFile, stat, rm } from "node:fs/promises";
import { applicationCompose, composeFile, credentialMounts, evaluationInvocation, retireHostRunner, withEvaluationLock } from "../docker.mjs";

/** Prepare an isolated checkout shape without reading private app settings. */
async function fixture(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), "suite docker $ literal "));
  t.after(() => rm(root, { recursive: true, force: true }));
  for (const dir of ["tft-chat/evals/langfuse/.runtime", "tft-chat/app/backend/src/domain/assistant_specs", "vod-review/backend", "vod-review/frontend/src"]) await mkdir(path.join(root, dir), { recursive: true });
  return root;
}

test("VOD preserves local absolute media paths, writable state and GPU optout", async (t) => {
  const root = await fixture(t);
  const gpu = await applicationCompose(root, { service: "vod", identity: "test" }, {});
  assert.equal(gpu.services.vod.gpus, "all");
  assert.deepEqual(gpu.services.vod.ports, ["127.0.0.1:8000:8000", "127.0.0.1:5174:8000"]);
  const model = await applicationCompose(root, { service: "vod", mode: "dev" }, { TFT_DOCKER_GPU: "0", VOD_DATA_DIR: "/original/data" });
  const backend = model.services.vod;
  assert.equal(backend.gpus, undefined);
  assert.equal(backend.environment.VOD_DATA_DIR, `${root}/vod-review/data`);
  assert.equal(backend.environment.VOD_WHISPER_DEVICE, "cpu");
  assert.equal(backend.environment.TFT_MEDIA_DIR, `${root}/media`);
  assert(backend.volumes.some((mount) => mount.source === `${root}/media` && mount.target === mount.source));
  assert(backend.volumes.some((mount) => mount.source === `${root}/vod-review/data` && mount.target === mount.source));
  assert.equal(model.services["vod-frontend"].environment.TFT_API_PROXY_TARGET, "http://vod:8000");
  assert(!model.services["vod-frontend"].volumes.some((mount) => mount.target.endsWith("node_modules")));
});

test("Chat retains complete DB settings, canonical tracing and editable specs", async (t) => {
  const root = await fixture(t);
  await writeFile(`${root}/tft-chat/.env`, "RDS_HOST=external.example\nRDS_DB=dev\nRDS_PORT=5432\nRDS_ADMIN=reader\nOPENAI_API_KEY='literal$token'\n");
  await writeFile(`${root}/tft-chat/chat_tft.ini`, "[chat]\nui_port=8300\n");
  await writeFile(`${root}/tft-chat/evals/langfuse/.env`, "LANGFUSE_PUBLIC_KEY=canonical\nLANGFUSE_SECRET_KEY=secret\n");
  const { services: { chat } } = await applicationCompose(root, { service: "chat", backendPort: 8301 }, { RDS_PORT: "5433", LANGFUSE_BASE_URL: "http://old" });
  assert.equal(chat.environment.RDS_HOST, "external.example");
  assert.equal(chat.environment.RDS_PORT, "5433");
  assert.equal(chat.environment.OPENAI_API_KEY, "literal$token");
  assert.equal(chat.environment.LANGFUSE_PUBLIC_KEY, "canonical");
  assert.equal(chat.environment.LANGFUSE_BASE_URL, "http://langfuse-web:3000");
  assert.equal(chat.environment.LANGFUSE_TRACING_ENABLED, "false");
  assert.equal(chat.environment.LANGFUSE_PUBLIC_URL, "http://localhost:15510");
  assert(chat.volumes.some((mount) => mount.target.endsWith("assistant_specs") && !mount.read_only));
  assert(chat.volumes.some((mount) => mount.target.endsWith("chat_tft.ini") && mount.read_only));
  const connected = await applicationCompose(root, { service: "chat" }, { TFT_DOCKER_EVAL_NETWORK: "tft-apps-evals_default" });
  assert.equal(connected.networks.evaluations.external, true);
  assert(connected.services.chat.networks.includes("evaluations"));
  assert.equal(connected.services.chat.environment.LANGFUSE_TRACING_ENABLED, undefined);
});

test("private Compose files retain literal dollar signs and owner-only access", async (t) => {
  const root = await fixture(t);
  const content = { services: { chat: { environment: { TOKEN: "a$secret${X}" }, volumes: ["$literal"] } } };
  const filename = await composeFile(root, content);
  assert.equal(JSON.parse(await readFile(filename, "utf8")).services.chat.environment.TOKEN, "a$$secret$${X}");
  assert.equal((await stat(filename)).mode & 0o777, 0o600);
  assert.equal(content.services.chat.environment.TOKEN, "a$secret${X}");
});

test("credential references must exist and are mounted read-only", async (t) => {
  const root = await fixture(t);
  assert.throws(() => credentialMounts({ VOD_GDRIVE_CLIENT_FILE: "relative.json" }, root), /absolute/);
  const client = `${root}/client.json`;
  await writeFile(client, "{}");
  assert.deepEqual(credentialMounts({ VOD_GDRIVE_CLIENT_FILE: client }, root), [{ type: "bind", source: client, target: client, read_only: true, bind: { create_host_path: false } }]);
});

test("test deployment override comes last and platform credentials are preserved", async (t) => {
  const root = await fixture(t);
  const envPath = `${root}/tft-chat/evals/langfuse/.env`;
  const saved = "LANGFUSE_PUBLIC_KEY=preserved\nLANGFUSE_SECRET_KEY=preserved-secret\n";
  await writeFile(envPath, saved);
  const invocation = await evaluationInvocation(root, { LANGFUSE_TEST_DEPLOYMENT: "1" });
  assert.equal(invocation.args.at(-1), `${root}/tft-chat/evals/langfuse/compose.test.yaml`);
  assert.equal(invocation.env.LANGFUSE_LLM_CONNECTION_WHITELISTED_HOST, "mock-model");
  assert.equal(await readFile(envPath, "utf8"), saved);
});

test("evaluation lifecycle ownership is exclusive and released after failure", async (t) => {
  const root = await fixture(t);
  await assert.rejects(withEvaluationLock(root, async () => {
    await assert.rejects(withEvaluationLock(root, async () => {}), /Another evaluation lifecycle/);
    throw new Error("operation failed");
  }), /operation failed/);
  assert.equal(await withEvaluationLock(root, async () => "recovered"), "recovered");
});

test("a reachable legacy runner hidden from the PID namespace is never retired", async (t) => {
  const root = await fixture(t);
  const runtime = `${root}/tft-chat/evals/langfuse/.runtime`;
  await writeFile(`${runtime}/runner.pid`, "2147483647");
  const server = http.createServer((_request, response) => response.end("healthy"));
  server.listen(`${runtime}/runner.sock`);
  await once(server, "listening");
  t.after(() => { server.closeAllConnections(); server.close(); });
  await assert.rejects(retireHostRunner(root), /ownership is hidden/);
  assert.equal(await readFile(`${runtime}/runner.pid`, "utf8"), "2147483647");
  await rm(`${runtime}/runner.pid`);
  await assert.rejects(retireHostRunner(root), /without an ownership receipt/);
});
