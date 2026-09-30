import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";
import { VideoRecord } from "./api";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const video: VideoRecord = { id: "v", original_name: "clip.mp4", mime_type: "video/mp4", duration: 10, width: 32, height: 32,
  created_at: "2026-09-05", box: { x: 0, y: 0, width: 1, height: 1, frame_time: 0 }, current_job: null, latest_job: null, active_job: null };
function mockApi() {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const payload = url.endsWith("/resumable-download") ? null : url.endsWith("/videos") ? [video] : url.endsWith("/from-url") ? { status: "failed", error: "Stopped test download" } : url.endsWith("/playback") ? { status: "failed", error: "Test playback unavailable" } : video;
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
}
it("sends download FPS alongside quality and checkpoint settings", async () => {
  const fetch = mockApi();
  render(<App />);
  await screen.findByRole("combobox", { name: "Recent videos" });
  fireEvent.change(screen.getByLabelText("Twitch or YouTube URL"), { target: { value: "https://youtu.be/example" } });
  fireEvent.change(screen.getByLabelText("Download target FPS"), { target: { value: "30" } });
  fireEvent.change(screen.getByLabelText("Download checkpoint interval in minutes"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "Download video from link" }));
  await screen.findByText("Stopped test download");
  const call = fetch.mock.calls.find(([url]) => String(url).endsWith("/from-url"));
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ target_fps: 30, quality: "720p", checkpoint_interval_seconds: 120 });
});
it.each(["Analyze", "Wisp classifier"])("sends a time-based interval from %s", async (mode) => {
  const fetch = mockApi();
  render(<App />);
  fireEvent.mouseDown(screen.getByRole("tab", { name: mode }), { button: 0, ctrlKey: false });
  fireEvent.change(await screen.findByLabelText("Recent videos"), { target: { value: "v" } });
  const interval = await screen.findByLabelText("Analysis interval in seconds");
  fireEvent.change(interval, { target: { value: "0.25" } });
  fireEvent.click(screen.getByRole("button", { name: "Process video" }));
  const endpoint = mode === "Analyze" ? "/videos/v/process" : "/videos/v/wisps/process";
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).endsWith(endpoint))).toBe(true));
  const call = fetch.mock.calls.find(([url]) => String(url).endsWith(endpoint));
  expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ sample_interval_seconds: 0.25 });
});


it("keeps polling wisp progress until completion with stable callbacks", async () => {
  let reads = 0;
  const job = { id: "job", status: "running", phase: "preparing", sample_interval_seconds: 0.5,
    batch_size: 64, total_samples: 100, progress: 0, collected_samples: 0, results: [], device: "cuda" };
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    let payload: unknown = video;
    if (url.endsWith("/resumable-download")) payload = null;
    else if (url.endsWith("/videos")) payload = [video];
    else if (url.includes("/detections?")) payload = { page: 1, pages: 1, total: 0, results: [] };
    else if (url.includes("/frame?")) payload = {
      sample_index: 0,
      frame_index: 0,
      timestamp: 0,
      confidence: 0,
      total: 1,
      ocr_text: null,
    };
    else if (url.endsWith("/playback")) payload = { status: "failed", error: "Test playback unavailable" };
    else if (url.endsWith("/wisps")) {
      reads += 1;
      if (reads < 4) {
        const active = { ...job, collected_samples: [0, 20, 60][reads - 1] };
        payload = { ...video, active_job: active, latest_job: active };
      } else {
        const completed = { ...job, status: "completed", phase: "completed", progress: 100, collected_samples: 100 };
        payload = { ...video, active_job: null, latest_job: completed, current_job: completed };
      }
    }
    return { ok: true, status: 200, json: async () => payload } as Response;
  });
  render(<App />);
  fireEvent.mouseDown(screen.getByRole("tab", { name: "Wisp classifier" }), { button: 0, ctrlKey: false });
  fireEvent.change(await screen.findByLabelText("Recent videos"), { target: { value: "v" } });
  expect(await screen.findByRole("button", { name: "Preparing 20%" }, { timeout: 2000 })).toBeDisabled();
  expect(await screen.findByRole("button", { name: "Preparing 60%" }, { timeout: 2000 })).toBeDisabled();
  expect(await screen.findByText("No wisps detected.", {}, { timeout: 2000 })).toBeInTheDocument();
  expect(reads).toBe(4);
});
