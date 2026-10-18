/** Browse shared resources and distill source text through the owned backend. */
const pageSize = 100;
const maxBytes = 10_000_000;

/** Carry only fixed user-facing failures across the renderer boundary. */
export class MediaError extends Error {}

/** Validate portable references without accepting URLs or filesystem paths. */
export function isMediaReference(value) {
  return typeof value === "string" && /^tft-resource:[a-f0-9]{32}$/.test(value);
}

/** Recognize text data without trying to decode arbitrary binary artifacts. */
export function isTextResource(resource) {
  const mime = resource.content_type?.split(";")[0].trim().toLowerCase() || "";
  return resource.kind === "text" || (resource.kind === "data" && (
    mime.startsWith("text/") || mime === "application/json" || mime.endsWith("+json")
    || /\.(json|jsonl|csv|tsv|txt|md|srt|vtt|xml|yaml|yml)$/i.test(resource.name)
  ));
}

/** Read a UTF-8 response with a byte cap, including chunked bodies. */
async function readBody(response) {
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) throw new MediaError("Text preview exceeds the 10 MB reading limit. You can still copy its reference.");
      chunks.push(value);
    }
    return new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks));
  } finally { await reader.cancel(); }
}

/** Return display metadata and portable identity, excluding untrusted URLs. */
function displayResource({ reference, name, source, size, kind, content_type }) {
  return { reference, name, source, size, kind, content_type };
}

/**
 * Create fixed catalogue operations without exposing arbitrary URLs to IPC.
 * Args:
 *   getOrigin: Current owned backend/proxy URL, unavailable during restart.
 *   request: HTTP implementation, replaceable by offline fixtures.
 * Returns:
 *   Handler for catalogue previews and explicit text distillation requests.
 */
export function createMediaReader(getOrigin, request = fetch) {
  return async (action, value) => {
    const origin = getOrigin();
    if (!origin) throw new MediaError("Media catalogue is unavailable while ChatTFT starts. Try again when it is ready.");
    const get = async (route) => {
      const response = await request(new URL(route, origin), {
        signal: AbortSignal.timeout(30_000), redirect: "error",
      });
      if (!response.ok) {
        const messages = {
          404: "This resource is no longer in the catalogue.",
          410: "The media file is missing from shared storage.",
          409: "The media failed its integrity check.",
          503: "The shared media catalogue is unavailable.",
        };
        await response.body?.cancel();
        throw new MediaError(messages[response.status] || "Could not read the shared media catalogue.");
      }
      return readBody(response);
    };
    if (action === "list") {
      const offset = value ?? 0;
      if (!Number.isSafeInteger(offset) || offset < 0) throw new MediaError("Invalid catalogue page.");
      const page = JSON.parse(await get(`/api/shared-media?limit=${pageSize}&offset=${offset}`));
      return {
        resources: page.map(displayResource),
        nextOffset: page.length === pageSize ? offset + pageSize : null,
      };
    }
    if (action === "read" || action === "distill") {
      if (!isMediaReference(value)) throw new MediaError("Invalid media reference.");
      const resource = JSON.parse(await get(`/api/shared-media/${value}`));
      const result = { resource: displayResource(resource) };
      const contentRoute = `/api/shared-media/${value}/content`;
      if (isTextResource(resource)) {
        if (resource.size > maxBytes) throw new MediaError("Text preview exceeds the 10 MB reading limit. You can still copy its reference.");
        result.text = await get(contentRoute);
      } else if (["image", "audio", "video"].includes(resource.kind)) {
        // Native elements use verified HTTP content and ranges directly instead
        // of buffering entire videos in the main process or sending them by IPC.
        result.contentUrl = new URL(contentRoute, origin).href;
      }
      if (action === "distill") {
        if (typeof result.text !== "string") throw new MediaError("Select a text or transcript resource to distill.");
        if (!result.text.trim()) throw new MediaError("This source is empty. Select text with content to distill.");
        // Resolve immutable source bytes in the main process. The renderer
        // supplies only a reference, never a model name, prompt, or arbitrary URL.
        const input = `Source metadata:\n${JSON.stringify(result.resource, null, 2)}\n\nSource text:\n${result.text}`;
        try {
          const response = await request(new URL("/api/assistants/tasks/transcription_pipeline/run", origin), {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input }), redirect: "error",
            signal: AbortSignal.timeout(600_000),
          });
          if (!response.ok) {
            await response.body?.cancel();
            throw new MediaError(response.status === 404
              ? "Distillation is unavailable. Restart ChatTFT to load the transcript assistant."
              : "Could not run distillation. Check that ChatTFT is ready and try again.");
          }
          const payload = JSON.parse(await readBody(response));
          if (payload.ok !== true || typeof payload.result !== "string" || !payload.result.trim()) {
            throw new MediaError("Distillation failed. Check ChatTFT's model configuration and source length, then try again.");
          }
          return { output: payload.result };
        } catch (error) {
          if (error instanceof MediaError) throw error;
          if (error.name === "TimeoutError") throw new MediaError("Distillation timed out. The assistant may still be running in ChatTFT.");
          throw new MediaError("Lost the distillation response. Check ChatTFT before retrying; the assistant may still be running.");
        }
      }
      return result;
    }
    if (action === "count") {
      if (typeof value !== "string" || Buffer.byteLength(value, "utf8") > maxBytes) {
        throw new MediaError("Text token counting is limited to 10 MB.");
      }
      try {
        const response = await request(new URL("/api/media/token-count", origin), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: value }), redirect: "error",
          signal: AbortSignal.timeout(30_000),
        });
        if (!response.ok) {
          await response.body?.cancel();
          throw new MediaError("Could not count tokens for this text.");
        }
        const result = JSON.parse(await readBody(response));
        if (!Number.isSafeInteger(result.token_count) || result.token_count < 0
          || result.tokenizer !== "o200k_base") throw new MediaError("Could not count tokens for this text.");
        return result;
      } catch (error) {
        if (error instanceof MediaError) throw error;
        throw new MediaError("Token count is unavailable. The o200k_base tokenizer may need to be cached by ChatTFT.");
      }
    }
    throw new MediaError("Unknown media action.");
  };
}
