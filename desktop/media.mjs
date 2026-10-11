/** Browse every shared resource through the desktop-owned backend. */
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
 *   Handler for listing every kind and loading bounded text or media previews.
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
    if (action === "read") {
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
      return result;
    }
    throw new MediaError("Unknown media action.");
  };
}
