import { describe, expect, it } from "vitest";

import { openAiTraceUrl } from "./openai.js";


describe("openAiTraceUrl", () => {
  it("deep-links to the encoded trace detail page", () => {
    expect(openAiTraceUrl("trace_abc/123")).toBe(
      "https://platform.openai.com/traces/trace?trace_id=trace_abc%2F123",
    );
  });
});
