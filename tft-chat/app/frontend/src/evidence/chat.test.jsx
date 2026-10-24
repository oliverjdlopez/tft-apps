import React from "react";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "../app.jsx";
import { rankingPresentation } from "./fixtures.js";
import { STREAM_EVENT_PREFIX, STREAM_EVENT_SUFFIX } from "../streaming.js";

/** Frame the same typed payload that the Python stream adapter emits. */
function frame(event) {
  return `\n${STREAM_EVENT_PREFIX}${btoa(JSON.stringify(event))}${STREAM_EVENT_SUFFIX}\n`;
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

it.each(["resolved", "unavailable", "unconfigured"])("keeps streamed answers and evidence visible with %s images through navigation and reset", async (imageState) => {
  localStorage.clear();
  const requests = [];
  const requestHeaders = [];
  const assetRequests = [];
  const config = {
    default_assistant: "chat",
    assistants: ["chat", "meta_expert"],
    default_model: "fake",
    reasoning_efforts: ["none", "low", "medium", "high", "xhigh"],
    models: [{ id: "fake", label: "Fake", key_configured: true }],
    tools: [],
    tool_groups: [],
    asset_context: { patch: "latest", set_number: imageState === "unconfigured" ? null : 17 },
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, options) => {
      if (url === "/api/config") return new Response(JSON.stringify(config));
      if (url === "/api/assets/resolve") {
        const body = JSON.parse(options.body);
        assetRequests.push(body);
        if (imageState === "unavailable") return new Response("Images unavailable", { status: 503 });
        return new Response(JSON.stringify({
          results: body.entities.map((entity) => ({
            status: "resolved", api_name: entity.name_or_id,
            src: `/media/tft/latest/set-17/en_us/files/${entity.name_or_id}.png`,
            asset_patch: "latest", fallback: false,
          })),
        }));
      }
      if (url !== "/api/chat") throw new Error(`Unexpected request: ${url}`);
      requestHeaders.push(options.headers);
      requests.push(JSON.parse(options.body));
      const body = `A grounded takeaway.${frame({ type: "text_part_complete" })}${frame({ type: "presentation", presentation: rankingPresentation("interactive_table", `view-${requests.length}`) })}`;
      const encoder = new TextEncoder();
      return new Response(
        new ReadableStream({
          start(controller) {
            // Deliberately split markers and payloads across transport chunks.
            for (let i = 0; i < body.length; i += 13)
              controller.enqueue(encoder.encode(body.slice(i, i + 13)));
            controller.close();
          },
        }),
      );
    }),
  );
  render(<App />);
  await screen.findByRole("option", { name: "Fake" });
  expect(screen.queryByRole("button", { name: /Base case|Easy|Medium|Hard|Handoff/ })).not.toBeInTheDocument();
  const input = screen.getByPlaceholderText(/Ask a TFT question/);
  const assistantSelect = screen.getByLabelText("Assistant");
  const modelSelect = screen.getByLabelText("Chat model");
  expect(assistantSelect.compareDocumentPosition(modelSelect) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(assistantSelect.closest(".composer")).toBeNull();
  expect(assistantSelect).toHaveValue("chat");
  expect(screen.getByRole("option", { name: "meta_expert" })).toBeInTheDocument();
  fireEvent.change(assistantSelect, { target: { value: "meta_expert" } });
  expect(screen.getByLabelText("Reasoning effort")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("Reasoning effort"), { target: { value: "high" } });
  expect(JSON.parse(localStorage.getItem("chatReasoningEffort"))).toBe("high");
  fireEvent.change(input, { target: { value: "Rank units" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("62.5%");
  expect(requests[0].reasoning_effort).toBe("high");
  expect(screen.getByText("A grounded takeaway.")).toBeInTheDocument();
  if (imageState === "unconfigured") {
    expect(assetRequests).toHaveLength(0);
    expect(document.querySelectorAll(".evidence-card .entity-icon")).toHaveLength(0);
  } else {
    await waitFor(() => expect(assetRequests).toHaveLength(1));
    expect(assetRequests[0]).toMatchObject({ patch: "latest", set_number: 17 });
    expect(assetRequests[0].entities).toEqual(expect.arrayContaining([
      { kind: "unit", name_or_id: "Jinx", role: "portrait" },
      { kind: "unit", name_or_id: "Annie", role: "portrait" },
    ]));
    if (imageState === "resolved") {
      await waitFor(() => expect(document.querySelectorAll("img.entity-icon-unit")).toHaveLength(3));
    } else {
      await screen.findByText(/entity images are unavailable; names remain visible/);
    }
    expect(screen.getByText("A grounded takeaway.")).toBeInTheDocument();
    expect(screen.getAllByText("Jinx")).toHaveLength(2);
  }
  fireEvent.click(screen.getByText("Explore table: sort, search and group"));
  fireEvent.change(screen.getByLabelText("Search loaded rows"), {
    target: { value: "Jinx" },
  });
  fireEvent.click(
    screen.getByRole("button", { name: "Developer", exact: true }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Chat", exact: true }));
  expect(screen.getByLabelText("Search loaded rows")).toHaveValue("Jinx");
  expect(requests).toHaveLength(1);
  expect(requestHeaders[0]["X-Chat-Assistant"]).toBe("meta_expert");
  fireEvent.change(input, { target: { value: "Another view" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await waitFor(() =>
    expect(screen.getAllByLabelText("Search loaded rows")).toHaveLength(2),
  );
  expect(
    requests[1].messages.every(
      (message) => Object.keys(message).sort().join() === "content,role",
    ),
  ).toBe(true);
  expect(screen.getAllByLabelText("Search loaded rows")[0]).toHaveValue("Jinx");
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "New conversation" }),
    ).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "New conversation" }));
  expect(screen.queryByLabelText("Search loaded rows")).not.toBeInTheDocument();
  expect(requests).toHaveLength(2);
});
