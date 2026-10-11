import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import type { VideoRecord } from "./api";
const adapter = { seek: vi.fn(), pause: vi.fn(), currentTime: () => 12 };
vi.mock("./YouTubePlayer", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return { YouTubePlayer: forwardRef((props: { sourceId: string; start: number }, ref) => {
    useImperativeHandle(ref, () => adapter);
    return <div data-testid="youtube-player" data-start={props.start}>{props.sourceId}</div>;
  }) };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); adapter.seek.mockClear(); adapter.pause.mockClear(); });
const round = { timestamp_seconds: 20, scheduled_timestamp_seconds: 20, timing_error_ms: 0, class_label: "21", confidence: 1 };
const video: VideoRecord = { id: "online", original_name: "Remote review", mime_type: "video/mp4", duration: 120, width: 1280, height: 720,
  created_at: "2026-10-11", mode: "online", source_id: "example1234", source_url: "https://youtu.be/example1234", source_start_seconds: 600, local_available: false,
  box: { x: .1, y: .1, width: .2, height: .1, frame_time: 0 }, current_job: null, latest_job: null, active_job: null };
function mockApi(record = video, overrides?: (url: string, options?: RequestInit) => unknown) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    const url = String(input);
    const payload = overrides?.(url, options) ?? (url.endsWith("/videos") ? [record] : url.endsWith("/resumable-download") || url.endsWith("/transcription") || url.endsWith("/gdrive-upload") ? null : record);
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
}
async function selectReview() {
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Recent videos"), { target: { value: "online" } });
  await screen.findByTestId("youtube-player");
}
it("imports YouTube online by default without requesting a download", async () => {
  const fetch = mockApi();
  render(<App />);
  fireEvent.change(screen.getByLabelText("Twitch or YouTube URL"), { target: { value: video.source_url } });
  fireEvent.click(screen.getByRole("button", { name: "Open online video from link" }));
  await screen.findByTestId("youtube-player");
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/videos/online"))).toBe(true);
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/from-url"))).toBe(false);
  expect(screen.getByLabelText("Analysis interval in seconds")).toHaveValue(10);
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/playback"))).toBe(false);
});
it("ignores hidden offline checkpoint settings when opening an online review", async () => {
  const fetch = mockApi();
  render(<App />);
  fireEvent.change(screen.getByLabelText("Import playback mode"), { target: { value: "offline" } });
  fireEvent.change(screen.getByLabelText("Download checkpoint interval in minutes"), { target: { value: "999" } });
  fireEvent.change(screen.getByLabelText("Import playback mode"), { target: { value: "online" } });
  fireEvent.change(screen.getByLabelText("Twitch or YouTube URL"), { target: { value: video.source_url } });
  expect(screen.queryByLabelText("Download checkpoint interval in minutes")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Open online video from link" }));
  await screen.findByTestId("youtube-player");
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/videos/online"))).toBe(true);
});
it("uses the review timeline and offset for round clicks and disables local media tools", async () => {
  const completed = { id: "job", status: "completed", results: [round], strategy: "online", sample_interval_seconds: 10 } as unknown as NonNullable<VideoRecord["current_job"]>;
  mockApi({ ...video, current_job: completed, latest_job: completed });
  await selectReview();
  expect(screen.getByTestId("youtube-player")).toHaveAttribute("data-start", "600");
  fireEvent.change(screen.getByLabelText("Seek offset in seconds"), { target: { value: "-3" } });
  fireEvent.click(screen.getByRole("button", { name: /21.*Jump/ }));
  expect(adapter.seek).toHaveBeenLastCalledWith(17, true);
  expect(screen.getByRole("button", { name: "Transcribe selected video" })).toBeDisabled();
  expect(screen.getByRole("button", { name: /Download selected/ })).toBeDisabled();
});
it("keeps online playback and results on failed offline conversion", async () => {
  mockApi(video, (url) => url.endsWith("/offline-download") ? { task_id: "d", status: "failed", progress: 0, error: "Offline copy failed" } : undefined);
  await selectReview();
  fireEvent.change(screen.getByLabelText("Review playback mode"), { target: { value: "offline" } });
  await screen.findByText("Offline copy failed");
  expect(screen.getByTestId("youtube-player")).toBeInTheDocument();
  expect(screen.getByLabelText("Review playback mode")).toHaveValue("online");
});
it("switches the same review to offline when its tracked download completes", async () => {
  const offline = { ...video, mode: "offline" as const, local_available: true };
  const fetch = mockApi(video, (url) => url.endsWith("/offline-download") ? { task_id: "d", status: "completed", progress: 100, video: offline } : url.endsWith("/playback") ? { status: "ready", manifest_url: "/manifest.m3u8" } : undefined);
  await selectReview();
  fireEvent.change(screen.getByLabelText("Review playback mode"), { target: { value: "offline" } });
  await waitFor(() => expect(screen.queryByTestId("youtube-player")).not.toBeInTheDocument());
  expect(screen.getByLabelText("Review playback mode")).toHaveValue("offline");
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/mode"))).toBe(false);
});
it("fetches a timestamped still for online drawing", async () => {
  const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
  const fetch = mockApi();
  fetch.mockImplementation(async (input) => {
    const url = String(input);
    if (url.includes("/frame?")) return { ok: true, headers: new Headers({ "X-Frame-Timestamp": "12.1" }), blob: async () => new Blob(["frame"]) } as Response;
    return { ok: true, status: 200, json: async () => url.endsWith("/videos") ? [video] : url.endsWith("/resumable-download") || url.endsWith("/transcription") ? null : video } as Response;
  });
  await selectReview();
  fireEvent.click(screen.getByRole("button", { name: "Edit box" }));
  expect(await screen.findByAltText("Still frame for drawing the round crop")).toHaveAttribute("src", "blob:preview");
  expect(adapter.pause).toHaveBeenCalled();
  expect(create).toHaveBeenCalled();
  expect(fetch.mock.calls.some(([url]) => String(url).includes("/frame?timestamp=12"))).toBe(true);
});
it("shows progressive online rounds and restores completed results after a failed rerun", async () => {
  let reads = 0;
  const completed = { id: "old", status: "completed", results: [round], strategy: "online", sample_interval_seconds: 10 } as unknown as NonNullable<VideoRecord["current_job"]>;
  const running = { ...completed, id: "new", status: "running", phase: "refining", results: [{ ...round, class_label: "31" }], total_samples: 10, collected_samples: 5, progress: 5 };
  mockApi({ ...video, current_job: completed, latest_job: completed }, (url) => {
    if (!url.endsWith("/videos/online")) return undefined;
    reads += 1;
    return reads === 1 ? { ...video, current_job: completed, latest_job: running, active_job: running } : { ...video, current_job: completed, latest_job: { ...running, status: "failed", phase: "failed", error: "Remote stream unavailable" }, active_job: null };
  });
  await selectReview();
  expect(screen.getByRole("button", { name: /31.*Jump/ })).toBeInTheDocument();
  expect(screen.getByLabelText("Review playback mode")).toBeDisabled();
  await screen.findByText("Remote stream unavailable", {}, { timeout: 2000 });
  expect(screen.getByRole("button", { name: /21.*Jump/ })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /31.*Jump/ })).not.toBeInTheDocument();
});
it("recovers this review's paused conversion independently of the latest global task", async () => {
  const fetch = mockApi(video, (url, options) => {
    if (url.endsWith('/resumable-download')) return { task_id: 'other-review', target_video_id: 'other', status: 'paused', progress: 10 };
    if (url.endsWith('/videos/online/offline-download') && !options?.method) return { task_id: 'this-review', target_video_id: 'online', status: 'paused', progress: 50 };
    if (url.endsWith('/downloads/this-review/dismiss')) return { dismissed: true };
    return undefined;
  });
  await selectReview();
  await screen.findByRole('button', { name: 'Resume offline download' });
  expect(screen.getByLabelText('Review playback mode')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Process video' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss offline download' }));
  await waitFor(() => expect(screen.getByLabelText('Review playback mode')).toBeEnabled());
  expect(fetch.mock.calls.some(([url]) => String(url).endsWith('/downloads/this-review/dismiss'))).toBe(true);
  expect(screen.getByLabelText('Review playback mode')).toHaveValue('online');
});
