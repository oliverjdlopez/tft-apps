import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { API_BASE } from "./api";
import WispFrameReview from "./WispFrameReview";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("only loads frame information while paused", async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue({ ok: true, json: async () => ({
    sample_index: 1, frame_index: 1, timestamp: 1, confidence: 0.9, total: 10, ocr_text: 'Paused text',
  }) } as Response);
  const seek = vi.fn();
  const { rerender } = render(<WispFrameReview videoId="v" jobId="j" time={0} paused={false} onSeek={seek} />);
  rerender(<WispFrameReview videoId="v" jobId="j" time={1} paused={false} onSeek={seek} />);
  expect(fetchMock).not.toHaveBeenCalled();
  rerender(<WispFrameReview videoId="v" jobId="j" time={1} paused onSeek={seek} />);
  expect(await screen.findByLabelText('Frame OCR text')).toHaveTextContent('Paused text');
  expect(fetchMock).toHaveBeenCalledTimes(1);
  rerender(<WispFrameReview videoId="v" jobId="j" time={2} paused={false} onSeek={seek} />);
  expect(screen.queryByLabelText('Frame OCR text')).not.toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(seek).not.toHaveBeenCalled();
});

it("requests the backend and displays confidence and OCR while stepping", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (url) => {
    const parsed = new URL(String(url));
    expect(parsed.origin).toBe(new URL(API_BASE).origin);
    const index = 2 + Number(parsed.searchParams.get("offset"));
    return { ok: true, json: async () => ({ sample_index: index, frame_index: index,
      timestamp: index / 30, confidence: 0.95, total: 10, ocr_text: `Text ${index}` }) } as Response;
  });
  const seek = vi.fn();
  render(<WispFrameReview videoId="v" jobId="j" time={2 / 30} onSeek={seek} />);
  expect(await screen.findByLabelText("Frame OCR text")).toHaveTextContent('Text 2');
  expect(screen.getByText(/Confidence: 95.00%/)).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/videos/v/wisps/jobs/j/frame?timestamp=${2 / 30}&offset=0`, undefined);
  fireEvent.change(screen.getByLabelText("Frames to skip"), { target: { value: "2" } });
  fireEvent.click(screen.getByLabelText("Skip frames forward"));
  await waitFor(() => expect(seek).toHaveBeenCalledWith(4 / 30));
  expect(screen.getByLabelText("Frame OCR text")).toHaveTextContent('Text 4');
});
