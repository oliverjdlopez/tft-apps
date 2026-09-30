import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ResponseTuningTab from "./ResponseTuningTab.jsx";

describe("ResponseTuningTab", () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      text: async () => JSON.stringify({
        ok: true,
        response_id: "resp_branch",
        assistant_output: "A revised answer.",
        output_items: [{ type: "message" }],
        usage: { total_tokens: 42 },
        request: { previous_response_id: "resp_parent" },
        prior_response: { id: "resp_parent" },
        latency_ms: 31,
      }),
    });
  });

  it("branches a response and renders prompt-tuning diagnostics", async () => {
    render(<ResponseTuningTab />);

    fireEvent.change(screen.getByPlaceholderText("resp_..."), {
      target: { value: "resp_parent" },
    });
    fireEvent.change(screen.getByPlaceholderText("Append a candidate follow-up prompt…"), {
      target: { value: "Try a more direct answer." },
    });
    fireEvent.click(screen.getByRole("button", { name: /run continuation/i }));

    await waitFor(() => expect(screen.getByText("A revised answer.")).toBeInTheDocument());
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/response-tuning/continue",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByText("resp_branch")).toBeInTheDocument();
    expect(screen.getByText("Token usage")).toBeInTheDocument();
  });
});
