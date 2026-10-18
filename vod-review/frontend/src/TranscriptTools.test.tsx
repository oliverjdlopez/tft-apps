import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TranscriptTools } from "./TranscriptTools";
import type { TranscriptionTask } from "./api";
const transcription: TranscriptionTask = { task_id: "speech", video_id: "video", status: "completed", progress: 100, transcript: "First. Correction.", language: "en", error: null };
const source = { ...transcription, segments: [{ id: "s000000", start: 12.25, end: 15.5, text: "First." }, { id: "s000001", start: 90.5, end: 94, text: " Correction." }] };
const evidence = { start_segment_id: "s000000", end_segment_id: "s000001", start_seconds: 12.25, end_seconds: 94, excerpt: "First. Correction." };
const completed = (name: string, output: unknown) => ({ name, active_run: null, latest_run: { status: "completed" }, successful_run: { id: name, status: "completed", output } });
function api(states: unknown[] = [], details: unknown = source) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    const payload = url.endsWith("/api/transcript-tasks") ? { tasks: [{ name: "transcription_pipeline", available: true }, { name: "find_key_moments", available: true }] } : url.endsWith("/tasks") ? { tasks: states } : options?.method === "POST" ? { status: "queued" } : details;
    return { ok: true, json: async () => payload } as Response;
  });
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); localStorage.clear(); });

it("loads saved output without starting either task and resolves segment highlights and fractional seeks", async () => {
  const fetch = api([completed("find_key_moments", { moments: [{ title: "Changed plan", explanation: "The speaker corrects the plan.", evidence: [evidence] }] })]);
  const seek = vi.fn();
  render(<TranscriptTools title="Example VOD" transcription={transcription} videoId="video" onSeek={seek} />);
  await screen.findByText("First.");
  fireEvent.click(screen.getByRole("tab", { name: "Key moments" }));
  fireEvent.click(screen.getByRole("button", { name: "0:12 · Changed plan" }));
  expect(seek).toHaveBeenCalledWith(12.25, true);
  fireEvent.click(screen.getByRole("button", { name: "Show in transcript" }));
  expect(screen.getByRole("tab", { name: "Transcript" })).toHaveAttribute("aria-selected", "true");
  expect(document.querySelectorAll('[data-highlighted="true"]')).toHaveLength(2);
  fireEvent.keyDown(screen.getByRole("tab", { name: "Transcript" }), { key: "ArrowLeft" });
  expect(screen.getByRole("tab", { name: "Distilled notes" })).toHaveFocus();
  expect(fetch.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});

it("starts actions independently and completion cannot take focus from a later selected tab", async () => {
  const fetch = api();
  render(<TranscriptTools title="Example" transcription={transcription} videoId="video" />);
  await waitFor(() => expect(screen.getByRole("button", { name: "Distill transcript" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "Distill transcript" }));
  fireEvent.click(screen.getByRole("button", { name: "Find key moments" }));
  fireEvent.click(screen.getByRole("tab", { name: "Transcript" }));
  await waitFor(() => expect(fetch.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(2));
  expect(screen.getByRole("tab", { name: "Transcript" })).toHaveAttribute("aria-selected", "true");
});

it("retains previous Markdown after a failed rerun and disables raw HTML", async () => {
  const state = completed("transcription_pipeline", "# Saved notes\n<script>unsafe()</script>\n\nOriginal prose.");
  api([{ ...state, latest_run: { status: "failed", error: "Network timeout" } }]);
  render(<TranscriptTools title="Example" transcription={transcription} videoId="video" />);
  fireEvent.click(screen.getByRole("tab", { name: "Distilled notes" }));
  await screen.findByRole("heading", { name: "Saved notes" });
  expect(screen.getByText("Original prose.")).toBeInTheDocument();
  expect(screen.getByText(/Rerun failed/)).toBeInTheDocument();
  expect(document.querySelector("script")).toBeNull();
  expect(screen.getByRole("button", { name: "Retry distill transcript" })).toBeEnabled();
});

it("renders audio timestamps as text and legacy transcripts without fabricated playback controls", async () => {
  api([], { ...source, video_id: null });
  const { rerender } = render(<TranscriptTools title="Audio" transcription={{ ...transcription, video_id: null }} />);
  await screen.findByText("0:12");
  expect(screen.queryByRole("button", { name: "0:12" })).not.toBeInTheDocument();
  api([], { ...source, task_id: "legacy", segments: null });
  rerender(<TranscriptTools title="Legacy audio" transcription={{ ...transcription, video_id: null, task_id: "legacy" }} />);
  await screen.findByText(/Reimport the audio source/);
  expect(screen.getByRole("button", { name: "Find key moments" })).toBeDisabled();
  expect(screen.getByLabelText("Transcript text")).toHaveValue(transcription.transcript);
});

it("ignores late source requests after switching video and transcript identities", async () => {
  let resolveOld: (value: Response) => void = () => {};
  const fetch = api([], { ...source, task_id: "new", video_id: "new-video", transcript: "New source", segments: [] });
  const original = fetch.getMockImplementation()!;
  fetch.mockImplementation((input, options) => String(input).includes('/transcriptions/speech?') ? new Promise(resolve => { resolveOld = resolve; }) : original(input, options));
  const { rerender } = render(<TranscriptTools title="Old" transcription={transcription} videoId="video" />);
  rerender(<TranscriptTools title="New" transcription={{ ...transcription, task_id: "new", video_id: "new-video", transcript: "New source" }} videoId="new-video" />);
  await waitFor(() => expect(screen.getByLabelText("Transcript text")).toHaveValue("New source"));
  await act(async () => resolveOld({ ok: true, json: async () => source } as Response));
  expect(screen.getByLabelText("Transcript text")).toHaveValue("New source");
});
