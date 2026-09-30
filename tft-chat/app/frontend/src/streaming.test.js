import { describe, expect, it } from "vitest";
import {
  consumeStreamBuffer,
  formatChatPart,
  STREAM_EVENT_PREFIX,
  STREAM_EVENT_SUFFIX,
} from "./streaming.js";

function frame(event) {
  return `\n${STREAM_EVENT_PREFIX}${btoa(JSON.stringify(event))}${STREAM_EVENT_SUFFIX}\n`;
}

describe("consumeStreamBuffer", () => {
  it("reassembles a framed event split across transport chunks", () => {
    const encoded = frame({ type: "tool", name: "rank_units" });
    const split = encoded.indexOf(STREAM_EVENT_PREFIX) + 8;
    const first = consumeStreamBuffer(encoded.slice(0, split));
    const second = consumeStreamBuffer(first.pending + encoded.slice(split));

    expect(first.events).toEqual([]);
    expect(second.events).toEqual([{ type: "tool", name: "rank_units" }]);
    expect(second.text).toBe("");
    expect(second.pending).toBe("");
  });

  it("keeps malformed frames visible instead of losing the answer", () => {
    const malformed = `${STREAM_EVENT_PREFIX}not-base64${STREAM_EVENT_SUFFIX}`;
    const result = consumeStreamBuffer(`Answer${malformed}`);

    expect(result.events).toEqual([]);
    expect(result.text).toContain("Answer");
    expect(result.text).toContain(malformed);
  });

  it("preserves text and part-completion event order from one transport chunk", () => {
    const complete = frame({ type: "text_part_complete" });
    const result = consumeStreamBuffer(`First${complete}Second`);

    expect(result.segments).toEqual([
      { type: "text", value: "First" },
      { type: "event", value: { type: "text_part_complete" } },
      { type: "text", value: "Second" },
    ]);
  });
});

describe("formatChatPart", () => {
  it("adds the requested label and two line breaks around visible content", () => {
    expect(formatChatPart("Answer", 2)).toBe("\n\n**response 2**\n\nAnswer");
  });
});
