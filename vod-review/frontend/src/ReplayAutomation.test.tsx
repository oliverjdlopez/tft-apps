import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import ReplayAutomation from "./ReplayAutomation";
import type { ReplayAutomationStatus } from "./api";

/** Provide a persistent schedule response without contacting creator platforms. */
function status(): ReplayAutomationStatus {
  return { configured: false, settings: { enabled: false, sources: [], daily_time: "09:00", timezone: "UTC", window_hours: 24, quality: "720p", transcribe: false }, next_run_at: null, runs: [], imports: [] };
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it("seeds existing creators and persists daily time, timezone and a window in days", async () => {
  let saved = status();
  let body: unknown;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, options) => {
    if (options?.method === "PUT") {
      body = JSON.parse(String(options.body));
      saved = { ...saved, settings: body as ReplayAutomationStatus["settings"], next_run_at: "2026-10-01T18:30:00Z" };
    }
    return { ok: true, json: async () => saved } as Response;
  });
  render(<ReplayAutomation sources={["https://www.youtube.com/@example"]} onClose={vi.fn()} onImported={vi.fn()} />);
  const creators = await screen.findByLabelText("Automatic import creators");
  expect(creators).toHaveValue("https://www.youtube.com/@example");
  fireEvent.click(screen.getByRole("checkbox", { name: "Enable daily imports" }));
  fireEvent.change(screen.getByLabelText("Daily import time"), { target: { value: "03:30" } });
  fireEvent.change(screen.getByLabelText("Import timezone"), { target: { value: "Asia/Tokyo" } });
  fireEvent.change(screen.getByLabelText("Import lookback amount"), { target: { value: "5" } });
  fireEvent.change(screen.getByLabelText("Import lookback unit"), { target: { value: "days" } });
  fireEvent.change(screen.getByLabelText("Automatic import quality"), { target: { value: "1080p" } });
  fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
  await screen.findByText("Schedule saved.");
  expect(body).toEqual({ enabled: true, sources: ["https://www.youtube.com/@example"], daily_time: "03:30", timezone: "Asia/Tokyo", window_hours: 120, quality: "1080p", transcribe: false });
  expect(screen.getByText(/Next scan:.*Asia\/Tokyo/)).toBeInTheDocument();
});

it("saves before Run now and exposes backend validation errors", async () => {
  const calls: string[] = [];
  const saved = status(); saved.settings.sources = ["https://www.twitch.tv/example"];
  let invalid = false;
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    calls.push(`${options?.method ?? "GET"} ${String(input).split("/api/")[1]}`);
    if (invalid && options?.method === "PUT") return { ok: false, json: async () => ({ detail: [{ msg: "Invalid creator URL" }] }) } as Response;
    return { ok: true, json: async () => String(input).endsWith("/run") ? { run_id: "run", status: "running" } : saved } as Response;
  });
  render(<ReplayAutomation sources={[]} onClose={vi.fn()} onImported={vi.fn()} />);
  await screen.findByLabelText("Automatic import creators");
  fireEvent.click(screen.getByRole("button", { name: "Run now" }));
  await screen.findByText("Creator scan started. Imported videos appear in the library.");
  expect(calls).toEqual(["GET replay-automation", "PUT replay-automation", "POST replay-automation/run", "GET replay-automation"]);
  invalid = true;
  fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid creator URL");
});

it("polls import progress without overwriting unsaved creators and refreshes the library", async () => {
  vi.useFakeTimers();
  const saved = status(); saved.settings.sources = ["https://www.youtube.com/@saved"];
  saved.runs = [{ id: "run", status: "running", scheduled_at: "2026-09-30T12:00:00Z", window_start: "2026-09-29T12:00:00Z", started_at: "2026-09-30T12:00:00Z", finished_at: null, matched: 2, imported: 0, skipped: 0, transcribed: 0, errors: [] }];
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => ({ ok: true, json: async () => structuredClone(saved) }) as Response);
  const refresh = vi.fn();
  let view: ReturnType<typeof render>;
  await act(async () => { view = render(<ReplayAutomation sources={["https://www.twitch.tv/local"]} onClose={vi.fn()} onImported={refresh} />); });
  expect(screen.getByLabelText("Automatic import creators")).toHaveValue("https://www.youtube.com/@saved");
  expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Automatic import creators"), { target: { value: "https://www.youtube.com/@draft" } });
  saved.runs[0].imported = 1;
  saved.runs[0].errors.push({ source_url: "https://www.twitch.tv/broken", message: "Creator unavailable" });
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByLabelText("Automatic import creators")).toHaveValue("https://www.youtube.com/@draft");
  expect(screen.getByText(/1 imported/)).toBeInTheDocument();
  expect(screen.getByText(/Creator unavailable/)).toBeInTheDocument();
  expect(refresh).toHaveBeenCalledOnce();
  view!.unmount();
  const calls = fetch.mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(fetch).toHaveBeenCalledTimes(calls);
});

it("rejects invalid windows before writing a schedule", async () => {
  const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => status() } as Response);
  render(<ReplayAutomation sources={[]} onClose={vi.fn()} onImported={vi.fn()} />);
  await screen.findByLabelText("Automatic import creators");
  fireEvent.change(screen.getByLabelText("Import lookback amount"), { target: { value: "0" } });
  // Submit directly to exercise application validation independently of native form constraints.
  fireEvent.submit(screen.getByRole("button", { name: "Save schedule" }).closest("form")!);
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("greater than zero"));
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("saves automatic transcription alongside creator sources and preserves it during progress polling", async () => {
  vi.useFakeTimers();
  const saved = status();
  const sourcesSaved = vi.fn();
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
    if (options?.method === "PUT") saved.settings = JSON.parse(String(options.body));
    return { ok: true, json: async () => String(input).endsWith("/run") ? { run_id: "run", status: "running" } : structuredClone(saved) } as Response;
  });
  await act(async () => { render(<ReplayAutomation sources={["https://www.twitch.tv/example"]} onClose={vi.fn()} onImported={vi.fn()} onSourcesSaved={sourcesSaved} />); });
  fireEvent.click(screen.getByRole("checkbox", { name: "Automatically transcribe imported videos" }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Run now" })); });
  expect(saved.settings.transcribe).toBe(true);
  expect(sourcesSaved).toHaveBeenCalledWith(["https://www.twitch.tv/example"]);
  expect(screen.getByText("Creator scan started. Videos and transcripts will appear in the library.")).toBeInTheDocument();
  saved.imports = [{ media_id: "twitch:one", title: "Saved VOD", source_url: saved.settings.sources[0], url: "https://www.twitch.tv/videos/one", status: "completed", progress: 100, error: null, video_id: "one", transcription_task_id: "text", transcription_status: "running", transcription_error: null }];
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText(/Video ready · Transcribing/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "Automatically transcribe imported videos" }));
  saved.imports[0].transcription_status = "failed";
  saved.imports[0].transcription_error = "No audio stream";
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText(/Transcription failed · No audio stream/)).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Automatically transcribe imported videos" })).not.toBeChecked();
});

it("keeps a deliberately cleared creator list and saved timezone when reopened", async () => {
  const saved = status(); saved.configured = true; saved.settings.timezone = "Asia/Tokyo";
  vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, json: async () => saved } as Response);
  render(<ReplayAutomation sources={["https://www.twitch.tv/old-browser-source"]} onClose={vi.fn()} onImported={vi.fn()} />);
  expect(await screen.findByLabelText("Automatic import creators")).toHaveValue("");
  expect(screen.getByLabelText("Import timezone")).toHaveValue("Asia/Tokyo");
});
