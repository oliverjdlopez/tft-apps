/** Exercise catalogue pagination, all resource kinds, and bounded reads offline. */
import assert from "node:assert/strict";
import test from "node:test";
import { createMediaReader, isTextResource, isMediaReference } from "../media.mjs";

const reference = `tft-resource:${"a".repeat(32)}`;
const resource = { reference, kind: "text", name: "Game transcript.txt", source: "youtube:example", size: 12, content_type: "text/plain" };

test("text detection preserves transcripts and JSON without decoding binary data", () => {
  assert.equal(isTextResource(resource), true);
  for (const name of ["statistics.json", "segments.json", "notes.txt", "subtitles.vtt"]) {
    assert.equal(isTextResource({ kind: "data", name }), true, name);
  }
  assert.equal(isTextResource({ kind: "data", name: "artifact", content_type: "application/vnd.example+json" }), true);
  assert.equal(isTextResource({ kind: "data", name: "model.bin", content_type: "application/octet-stream" }), false);
  assert.equal(isTextResource({ kind: "video", name: "transcript.mp4" }), false);
});

test("listing includes every media kind in one unfiltered catalogue page", async () => {
  let calls = 0;
  const kinds = ["video", "audio", "image", "text", "data"];
  const reader = createMediaReader(() => "http://127.0.0.1:9999", async (url, options) => {
    calls++;
    assert.equal(options.redirect, "error");
    assert(options.signal instanceof AbortSignal);
    assert.equal(url.searchParams.has("kind"), false);
    assert.equal(url.searchParams.get("offset"), "200");
    return Response.json(Array.from({ length: 100 }, (_, index) => ({ ...resource, kind: kinds[index % 5], content_url: "file:///private" })));
  });
  const result = await reader("list", 200);
  assert.equal(result.resources.length, 100);
  assert.equal(result.nextOffset, 300);
  assert.deepEqual([...new Set(result.resources.map((item) => item.kind))], kinds);
  assert.equal(result.resources[0].content_url, undefined);
  assert.equal(calls, 1);
  await assert.rejects(reader("list", -1), /Invalid catalogue page/);
});

test("reading text inspects metadata then uses the fixed verified-content route", async () => {
  const paths = [];
  const reader = createMediaReader(() => "http://127.0.0.1:9999", async (url) => {
    paths.push(url.pathname);
    return url.pathname.endsWith("/content") ? new Response("Hello world!") : Response.json(resource);
  });
  assert.deepEqual(await reader("read", reference), { resource, text: "Hello world!" });
  assert.deepEqual(paths, [`/api/shared-media/${reference}`, `/api/shared-media/${reference}/content`]);
  for (const value of ["../../secret", "https://example.com", `${reference}/content`, null]) {
    assert.equal(isMediaReference(value), false);
    await assert.rejects(reader("read", value), /Invalid media reference/);
  }
  assert.equal(paths.length, 2);
});

test("binary media uses fixed streaming URLs and arbitrary data remains referenceable", async () => {
  for (const kind of ["audio", "video", "image", "data"]) {
    let requests = 0;
    const item = { ...resource, kind, name: "artifact.bin", content_type: "application/octet-stream", size: 100_000_000, content_url: "https://untrusted.example/private" };
    const reader = createMediaReader(() => "http://127.0.0.1:9999", async () => {
      requests++;
      return Response.json(item);
    });
    const result = await reader("read", reference);
    assert.equal(result.resource.reference, reference);
    assert.equal(result.text, undefined);
    assert.equal(result.contentUrl, kind === "data" ? undefined : `http://127.0.0.1:9999/api/shared-media/${reference}/content`);
    assert.equal(requests, 1, "binary files are not buffered through IPC");
  }
});

test("oversized text is rejected before transferring content", async () => {
  let requests = 0;
  const reader = createMediaReader(() => "http://127.0.0.1:9999", async () => {
    requests++;
    return Response.json({ ...resource, size: 10_000_001 });
  });
  await assert.rejects(reader("read", reference), /10 MB/);
  assert.equal(requests, 1);
});

test("missing, corrupt, disabled and restarting catalogue failures are actionable", async () => {
  for (const [status, message] of [[404, /no longer/], [410, /missing/], [409, /integrity/], [503, /unavailable/]]) {
    const reader = createMediaReader(() => "http://127.0.0.1:9999", async () => new Response("private backend detail", { status }));
    await assert.rejects(reader("read", reference), message);
  }
  await assert.rejects(createMediaReader(() => undefined)("list", 0), /while ChatTFT starts/);
});

test("streamed responses enforce the size cap even when metadata understates size", async () => {
  let cancelled = false;
  const reader = createMediaReader(() => "http://127.0.0.1:9999", async (url) => (
    url.pathname.endsWith("/content") ? new Response(new ReadableStream({
      pull(controller) { controller.enqueue(new Uint8Array(1_000_001)); },
      cancel() { cancelled = true; },
    })) : Response.json(resource)
  ));
  await assert.rejects(reader("read", reference), /10 MB/);
  assert.equal(cancelled, true);
});
