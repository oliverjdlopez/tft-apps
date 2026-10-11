/** Check credential handling and the session handshake without a live server. */
import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_LANGFUSE_URL, localLangfuseUrl, readLangfuseSettings, signInLangfuse } from "../langfuse.mjs";

const settings = { url: "http://localhost:15510/project/tft-apps-evals", email: "fixture@example.test", password: "fixture &+ password" };

function fixture(responses) {
  const calls = [];
  let flushes = 0;
  return {
    calls, get flushes() { return flushes; },
    cookies: { async flushStore() { flushes++; } },
    async fetch(url, options) {
      calls.push({ url, options });
      const response = responses.shift();
      if (response instanceof Error) throw response;
      return new Response(JSON.stringify(response), { status: 200 });
    },
  };
}

test("only the required local settings are read, preserving quoted passwords", () => {
  let filename;
  const result = readLangfuseSettings("/suite", { read(file) {
    filename = file;
    return 'LANGFUSE_INIT_USER_EMAIL=fixture@example.test\nLANGFUSE_INIT_USER_PASSWORD="fixture &+ password"\nLANGFUSE_DESKTOP_URL=http://localhost:15510/project/tft-apps-evals\nDATABASE_PASSWORD=unrelated';
  } });
  assert.equal(filename, "/suite/tft-chat/evals/langfuse/.env");
  assert.deepEqual(result, settings);
});

test("Windows Electron reads the original WSL checkout, not its staged shell", () => {
  let filename;
  readLangfuseSettings("/home/some user/tft-apps", {
    platform: "win32", wsl: { distro: "Ubuntu" }, read(file) { filename = file; return ""; },
  });
  assert.equal(filename, "\\\\wsl.localhost\\Ubuntu\\home\\some user\\tft-apps\\tft-chat\\evals\\langfuse\\.env");
});

test("missing settings and explicit opt-out keep manual sign-in available", async () => {
  const warnings = [];
  assert.deepEqual(readLangfuseSettings("/missing", {
    read() { throw Object.assign(new Error("private path"), { code: "ENOENT" }); }, warn: line => warnings.push(line),
  }), { url: DEFAULT_LANGFUSE_URL });
  const optedOut = readLangfuseSettings("/suite", { read: () => "LANGFUSE_DESKTOP_AUTO_LOGIN=false\nLANGFUSE_INIT_USER_EMAIL=user\nLANGFUSE_INIT_USER_PASSWORD=secret" });
  assert.deepEqual(optedOut, { url: DEFAULT_LANGFUSE_URL });
  const partition = fixture([]);
  assert.equal(await signInLangfuse(partition, optedOut), false);
  assert.equal(partition.calls.length, 0);
  assert.deepEqual(warnings, []);
});

test("invalid settings disable automatic sign-in without logging their contents", () => {
  const warnings = [];
  const result = readLangfuseSettings("/suite", {
    read: () => "LANGFUSE_DESKTOP_URL=https://private-secret@example.com\nLANGFUSE_INIT_USER_PASSWORD=secret",
    warn: line => warnings.push(line),
  });
  assert.deepEqual(result, { url: DEFAULT_LANGFUSE_URL });
  assert.equal(warnings.length, 1);
  assert.doesNotMatch(warnings[0], /private-secret|example.com/);
});

test("automatic authentication rejects remote URLs and credentials in URLs", async () => {
  for (const url of ["https://example.com", "http://localhost.example.com", "file:///tmp/local", "http://user:secret@localhost:15510", "http://localhost:15510/?password=secret", "http://localhost:15510/#secret"]) {
    assert.throws(() => localLangfuseUrl(url));
    const partition = fixture([]);
    assert.equal(await signInLangfuse(partition, { ...settings, url }, { warn() {} }), false);
    assert.equal(partition.calls.length, 0);
  }
});

test("an existing session is reused without submitting any password", async () => {
  const partition = fixture([{ user: { email: "chosen-account@example.test" } }]);
  assert.equal(await signInLangfuse(partition, settings), true);
  assert.equal(partition.calls.length, 1);
  assert.equal(partition.calls[0].options.body, undefined);
  assert.equal(partition.flushes, 0);
});

test("a fresh session uses CSRF and the same cookie jar, then verifies and persists login", async () => {
  const partition = fixture([{}, { csrfToken: "fixture-csrf" }, { url: settings.url }, { user: { email: settings.email } }]);
  assert.equal(await signInLangfuse(partition, settings), true);
  assert.deepEqual(partition.calls.map(call => new URL(call.url).pathname), [
    "/api/auth/session", "/api/auth/csrf", "/api/auth/callback/credentials", "/api/auth/session",
  ]);
  for (const call of partition.calls) {
    assert.equal(new URL(call.url).origin, "http://localhost:15510");
    assert.equal(call.options.redirect, "error");
    assert.equal(call.options.credentials, "include");
    assert.equal(call.options.signal, partition.calls[0].options.signal);
    assert.doesNotMatch(call.url, /password|fixture-csrf/);
  }
  const post = partition.calls[2].options;
  assert.equal(post.method, "POST");
  assert.equal(new URLSearchParams(post.body).get("password"), settings.password);
  assert.equal(new URLSearchParams(post.body).get("csrfToken"), "fixture-csrf");
  assert.equal(partition.flushes, 1);
});

test("failed authentication and missing CSRF fall back without disclosing server errors", async () => {
  for (const responses of [
    [new Error("server echoed private-password")],
    [{}, {}],
    [{}, { csrfToken: "csrf" }, { url: "http://localhost:15510/auth/error" }, {}],
  ]) {
    const warnings = [];
    const partition = fixture(responses);
    assert.equal(await signInLangfuse(partition, settings, { warn: line => warnings.push(line) }), false);
    assert.equal(partition.flushes, 0);
    assert.equal(warnings.length, 1);
    assert.doesNotMatch(warnings[0], /private-password|fixture/);
  }
});

test("authentication has one bounded deadline across all requests", async () => {
  const warnings = [];
  let aborted = false;
  const partition = {
    fetch(_url, { signal }) {
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error("deadline not enforced")), 1000);
        signal.addEventListener("abort", () => { aborted = true; clearTimeout(timer); reject(signal.reason); }, { once: true });
      });
    },
  };
  assert.equal(await signInLangfuse(partition, settings, { timeout: 10, warn: line => warnings.push(line) }), false);
  assert.equal(aborted, true);
  assert.equal(warnings.length, 1);
});
