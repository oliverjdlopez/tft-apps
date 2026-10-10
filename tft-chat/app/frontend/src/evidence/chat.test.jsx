import { AssistantName } from "../assistant-names.js";
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

it("streams evidence into its answer, preserves controls through navigation, and clears on reset", async () => {
  localStorage.clear();
  const requests = [];
  const requestHeaders = [];
  const config = {
    default_assistant: AssistantName.CHAT,
    assistants: [AssistantName.CHAT, AssistantName.META_EXPERT],
    default_model: "fake",
    models: [{ id: "fake", label: "Fake", key_configured: true }],
    tools: [],
    tool_groups: [],
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url, options) => {
      if (url === "/api/config") return new Response(JSON.stringify(config));
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
  expect(assistantSelect).toHaveValue(AssistantName.CHAT);
  expect(screen.getByRole("option", { name: AssistantName.META_EXPERT })).toBeInTheDocument();
  fireEvent.change(assistantSelect, { target: { value: AssistantName.META_EXPERT } });
  fireEvent.change(input, { target: { value: "Rank units" } });
  fireEvent.keyDown(input, { key: "Enter" });
  await screen.findByText("62.5%");
  expect(screen.getByText("A grounded takeaway.")).toBeInTheDocument();
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
  expect(requestHeaders[0]["X-Chat-Assistant"]).toBe(AssistantName.META_EXPERT);
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
