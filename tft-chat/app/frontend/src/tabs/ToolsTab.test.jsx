import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ToolsTab from "./ToolsTab.jsx";


function jsonResponse(value) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}


afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("ToolsTab", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses backend invocation requirements for argument badges", async () => {
    const strictSchema = {
      type: "object",
      properties: {
        count: { type: "integer" },
        label: { anyOf: [{ type: "string" }, { type: "null" }] },
        limit: { type: "integer", default: 10 },
      },
      required: ["count", "label", "limit"],
    };
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      groups: [{
        key: "sample",
        label: "Sample",
        description: "Sample tools",
        tools: [{
          name: "sample_tool",
          description: "Exercise one sample tool.",
          input_schema: strictSchema,
          invocation_schema: { ...strictSchema, required: ["count"] },
          output_schema: {},
        }],
      }],
    })));

    render(<ToolsTab />);
    fireEvent.click(await screen.findByText("sample_tool"));

    expect(screen.getAllByText("required")).toHaveLength(1);
    expect(screen.getByText("count").closest("label")).toHaveTextContent("required");
    expect(screen.getByText("label").closest("label")).not.toHaveTextContent("required");
    expect(screen.getByText("limit").closest("label")).not.toHaveTextContent("required");
  });
});

it("preserves typed tool arguments and omits unset optional values", async () => {
  const schema = { type: "object", properties: {
    count: { type: "integer" }, enabled: { type: "boolean" }, tags: { type: "array" }, optional: { type: "string" },
  }, required: ["count"] };
  const fetch = vi.fn(async (path, options) => jsonResponse(options?.method === "POST"
    ? { ok: true, elapsed_ms: 1, structured: { count: 3 } }
    : { groups: [{ key: "fixture", label: "Fixture", tools: [{ name: "fixture", input_schema: schema, invocation_schema: schema }] }] }));
  vi.stubGlobal("fetch", fetch);
  render(<ToolsTab />);
  fireEvent.click(await screen.findByRole("button", { name: "fixture" }));
  fireEvent.change(screen.getByLabelText(/count/), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("enabled"), { target: { value: "false" } });
  fireEvent.change(screen.getByLabelText("tags"), { target: { value: "alpha, beta" } });
  fireEvent.click(screen.getByRole("button", { name: "call tool" }));
  const [, options] = fetch.mock.calls.find(([path]) => path === "/api/tools/call");
  expect(JSON.parse(options.body)).toEqual({ name: "fixture", arguments: { count: 3, enabled: false, tags: ["alpha", "beta"] } });
});
