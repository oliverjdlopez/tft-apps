import {fireEvent, render, screen, waitFor} from "@testing-library/react";
import {beforeEach, describe, expect, it, vi} from "vitest";
import SpecsTab from "./SpecsTab.jsx";

describe("SpecsTab after Promptfoo migration", () => {
  beforeEach(() => {
    global.fetch = vi.fn(async (path, options = {}) => {
      const document = {id: "doc", assistant: "chat", label: "system.md", path: "system.md", language: "markdown",
        content: options.method === "PUT" ? "Edited prompt" : "Original prompt", revision: "revision", test_suites: ["chat"]};
      const data = path === "/api/specs" ? {assistants: [{name: "chat", description: "Chat", model: "default", eval_suites: ["chat"],
        sources: [{document_id: "doc", label: "system.md", path: "system.md"}]}]} : document;
      return {ok: true, text: async () => JSON.stringify(data)};
    });
  });

  it("saves and validates specs without calling the retired eval endpoint", async () => {
    render(<SpecsTab />);
    fireEvent.click(await screen.findByRole("button", {name: /system.md/}));
    fireEvent.change(await screen.findByRole("textbox", {name: "Edit system.md"}), {target: {value: "Edited prompt"}});
    fireEvent.click(screen.getByRole("button", {name: "Save & validate"}));
    await waitFor(() => expect(screen.getByText("Saved and validated system.md.")).toBeInTheDocument());
    expect(global.fetch.mock.calls.some(([path]) => path.startsWith("/api/evals"))).toBe(false);
    expect(screen.queryByRole("button", {name: /save & run/i})).not.toBeInTheDocument();
  });
});
