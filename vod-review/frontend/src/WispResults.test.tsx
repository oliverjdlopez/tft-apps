import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import WispResults from "./WispResults";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("pages thousands of timestamps in bounded chunks and seeks the exact frame time", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const page = Number(new URL(String(url)).searchParams.get("page"));
    return { ok: true, json: async () => ({ page, pages: 100, total: 2500,
      results: Array.from({ length: 25 }, (_, n) => ({ frame_index: (page - 1) * 25 + n, timestamp_seconds: ((page - 1) * 25 + n) / 30, confidence: 1 })) }) } as Response;
  });
  const seek = vi.fn();
  render(<WispResults videoId="v" jobId="j" onSeek={seek} />);
  await screen.findByText("2,500 matching frames");
  expect(screen.getAllByRole("button", { name: /Jump to wisp/ })).toHaveLength(25);
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  await screen.findByText("Page 2 of 100 · 25 per page");
  fireEvent.click(screen.getAllByRole("button", { name: /Jump to wisp/ })[0]);
  expect(seek).toHaveBeenCalledWith(25 / 30);
  expect(fetchMock).toHaveBeenLastCalledWith(expect.stringContaining("page=2"), undefined);
  fireEvent.click(screen.getByRole("button", { name: "Page 100" }));
  await screen.findByText("Page 100 of 100 · 25 per page");
  expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
  expect(screen.getAllByRole("button", { name: /^Page / }).length).toBeLessThanOrEqual(5);
});

it("distinguishes no detections from a failed request and allows retry", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("Offline")).mockResolvedValue({ ok: true, json: async () => ({ page: 1, pages: 1, total: 0, results: [] }) } as Response);
  render(<WispResults videoId="v" jobId="j" onSeek={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Offline");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("No wisps detected.")).toBeInTheDocument();
  expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
});
