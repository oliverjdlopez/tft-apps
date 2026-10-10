import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App, { buildRoundExportClips, getSeekTimestamp, groupRoundTransitions, isFeaturedRound, parseTimestamp } from "./App";
import type { SampleResult, VideoRecord } from "./api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("replay discovery", () => {
  it("saves channel settings and lists discovered replays", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, options) => {
      const url = String(input);
      if (url.endsWith("/api/replay-automation")) {
        const settings = options?.method === "PUT" ? JSON.parse(String(options.body)) : {
          enabled: false, sources: [], daily_time: "09:00", timezone: "UTC", window_hours: 24, quality: "720p", transcribe: false,
        };
        return { ok: true, json: async () => ({ settings, next_run_at: null, runs: [], imports: [] }) } as Response;
      }
      if (url.endsWith("/api/resumable-download")) {
        return { ok: true, status: 200, json: async () => null } as Response;
      }
      if (url.endsWith("/api/replays/discover")) {
        return {
          ok: true,
          status: 200,
          json: async () => ({
            replays: [{
              id: "youtube:abc123",
              platform: "youtube",
              title: "Fresh tournament VOD",
              creator: "Example Channel",
              url: "https://www.youtube.com/watch?v=abc123",
              source_url: "https://www.youtube.com/@example",
              thumbnail_url: null,
              duration_seconds: 3661,
              published_at: "2026-09-15T12:00:00Z",
            }],
            errors: [],
          }),
        } as Response;
      }
      return { ok: true, status: 200, json: async () => [] } as Response;
    });

    render(<App />);
    await screen.findByText("No videos yet");
    fireEvent.click(screen.getByRole("button", { name: "Replay source settings" }));
    fireEvent.change(await screen.findByLabelText("Automatic import creators"), {
      target: { value: "https://www.youtube.com/@example" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    await screen.findByText("Schedule saved.");
    fireEvent.click(screen.getByRole("button", { name: "Close source settings" }));

    expect(JSON.parse(window.localStorage.getItem("framewise.replaySources") ?? "[]")).toEqual([
      "https://www.youtube.com/@example",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Display new replays" }));
    expect(await screen.findByText("Fresh tournament VOD")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Use replay" }));
    expect(screen.getByLabelText("Twitch or YouTube URL")).toHaveValue("https://www.youtube.com/watch?v=abc123");
  });

  it("opens settings when no replay sources have been configured", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => ({
      ok: true,
      status: 200,
      json: async () => String(input).endsWith("/api/resumable-download") ? null : [],
    } as Response));
    render(<App />);
    await screen.findByText("No videos yet");
    fireEvent.click(screen.getByRole("button", { name: "Display new replays" }));
    expect(screen.getByRole("dialog", { name: "Sources and automation" })).toBeInTheDocument();
  });
});

describe("App workspace modes", () => {
  it("opens the round analysis workspace directly", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({ ok: true, status: 200, json: async () => [] } as Response);
    render(<App />);
    expect(screen.getByText("Find the moment that matters.")).toBeInTheDocument();
  });
});

describe("VOD download range", () => {
  it("parses minute and hour timestamps", () => {
    expect(parseTimestamp("")).toBeNull();
    expect(parseTimestamp("12:34")).toBe(754);
    expect(parseTimestamp("1:02:03")).toBe(3723);
    expect(parseTimestamp("1:60")).toBeNull();
    expect(parseTimestamp("later")).toBeNull();
  });

  it("rejects an end timestamp before the start", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    } as Response);
    render(<App />);
    await screen.findByText("No videos yet");
    fireEvent.change(screen.getByLabelText("Twitch or YouTube URL"), { target: { value: "https://youtu.be/example" } });
    fireEvent.change(screen.getByLabelText("Download start timestamp"), { target: { value: "2:00" } });
    fireEvent.change(screen.getByLabelText("Download end timestamp"), { target: { value: "1:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Download video from link" }));

    expect(await screen.findByText("The end timestamp must be after the start timestamp.")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/api/videos/from-url"))).toBe(false);
  });

  it("sends the optional checkpoint interval and exposes paused downloads", async () => {
    const partialVideo: VideoRecord = {
      id: "partial-1",
      original_name: "Checkpoint VOD (paused checkpoint).mp4",
      mime_type: "video/mp4",
      duration: 300,
      width: 1920,
      height: 1080,
      created_at: "2026-08-27T00:00:00Z",
      box: null,
      current_job: null,
      active_job: null,
      latest_job: null,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/api/resumable-download")) {
        return { ok: true, status: 200, json: async () => null } as Response;
      }
      if (url.endsWith("/api/videos/from-url")) {
        return { ok: true, status: 202, json: async () => ({ task_id: "download-1", status: "paused", progress: 25, video: partialVideo }) } as Response;
      }
      return { ok: true, status: 200, json: async () => [] } as Response;
    });
    render(<App />);
    await screen.findByText("No videos yet");
    fireEvent.change(screen.getByLabelText("Twitch or YouTube URL"), { target: { value: "https://youtu.be/example" } });
    fireEvent.change(screen.getByLabelText("Download checkpoint interval in minutes"), { target: { value: "5" } });
    expect(screen.getByLabelText("Download video quality")).toHaveValue("720p");
    fireEvent.change(screen.getByLabelText("Download video quality"), { target: { value: "480p" } });
    fireEvent.click(screen.getByRole("button", { name: "Download video from link" }));

    expect(await screen.findByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Use saved footage/i })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: /Checkpoint VOD/ })).toBeInTheDocument();
    const request = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/api/videos/from-url"));
    expect(JSON.parse(String(request?.[1]?.body))).toMatchObject({ checkpoint_interval_seconds: 300, quality: "480p" });
    fireEvent.click(screen.getByRole("button", { name: /Dismiss/i }));
    await waitFor(() => expect(screen.queryByText("Download paused")).not.toBeInTheDocument());
  });
});


describe("game detection", () => {
  const sampleResults = (labels: string[], timestamps?: number[]): SampleResult[] => labels.map((class_label, index) => ({
    timestamp_seconds: timestamps?.[index] ?? index * 10,
    scheduled_timestamp_seconds: timestamps?.[index] ?? index * 10,
    timing_error_ms: 0,
    class_label,
    confidence: 0.9,
  }));

  it("groups round transitions when the stage resets to stage one", () => {
    const labels = ["11", "12", "21", "22", "31", "11", "12", "21"];
    const results = sampleResults(labels);

    const games = groupRoundTransitions(results);

    expect(games).toHaveLength(2);
    expect(games[0].results.map((result) => result.class_label)).toEqual(["11", "12", "21", "22", "31"]);
    expect(games[1].results.map((result) => result.class_label)).toEqual(["11", "12", "21"]);
  });

  it("does not split on regressions that remain after stage one", () => {
    const labels = ["11", "12", "21", "22", "21", "31"];
    const results = sampleResults(labels);

    expect(groupRoundTransitions(results)).toHaveLength(1);
  });

  it("does not turn late-game stage-one artifacts into short games", () => {
    const results = sampleResults(["11", "12", "21", "31", "17", "24", "15", "32", "41"]);

    expect(groupRoundTransitions(results)).toHaveLength(1);
  });

  it("waits for an ordered opening sequence before confirming a new game", () => {
    const results = sampleResults(["11", "12", "21", "31", "11", "32", "11", "12", "13", "21", "22"]);

    const games = groupRoundTransitions(results);

    expect(games).toHaveLength(2);
    expect(games[0].results.map((result) => result.class_label)).toEqual(["11", "12", "21", "31", "11", "32"]);
    expect(games[1].results.map((result) => result.class_label)).toEqual(["11", "12", "13", "21", "22"]);
  });

  it("tolerates one incorrect classification within an opening sequence", () => {
    const results = sampleResults(["11", "12", "21", "31", "11", "51", "12", "13", "21"]);

    expect(groupRoundTransitions(results)).toHaveLength(2);
  });

  it("does not combine distant artifacts into opening evidence", () => {
    const labels = ["11", "12", "21", "31", "11", "32", "12", "13", "21"];
    const timestamps = [0, 10, 20, 30, 40, 50, 1_000, 1_010, 1_020];

    const games = groupRoundTransitions(sampleResults(labels, timestamps));

    expect(games).toHaveLength(2);
    expect(games[1].results[0].class_label).toBe("12");
  });

  it("shows key rounds by default and reveals the remaining clickable rounds", async () => {
    const labels = ["11", "12", "21", "22", "31", "32", "33", "41", "42"];
    const results: SampleResult[] = labels.map((class_label, index) => ({
      timestamp_seconds: index * 10,
      scheduled_timestamp_seconds: index * 10,
      timing_error_ms: 0,
      class_label,
      confidence: 0.9,
    }));
    const job = {
      id: "job-1",
      status: "completed" as const,
      progress: results.length,
      total_samples: results.length,
      collected_samples: results.length,
      batch_size: 64,
      sample_interval_seconds: 5,
      reuse_cached_crops: false,
      source_job_id: null,
      phase: "completed" as const,
      max_timing_error_ms: 0,
      device: "cpu",
      error: null,
      created_at: "2026-08-19T00:00:00Z",
      updated_at: "2026-08-19T00:00:00Z",
      results,
    };
    const video: VideoRecord = {
      id: "video-1",
      original_name: "Round visibility test.mp4",
      mime_type: "video/mp4",
      duration: 600,
      width: 1920,
      height: 1080,
      created_at: "2026-08-19T00:00:00Z",
      box: { x: 0.1, y: 0.1, width: 0.2, height: 0.2, frame_time: 0 },
      current_job: job,
      active_job: null,
      latest_job: job,
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).endsWith("/round-export")) {
        return { ok: true, status: 200, blob: async () => new Blob(["video"]) } as Response;
      }
      return {
        ok: true,
        status: 200,
        json: async () => String(input).endsWith("/api/videos") ? [video] : video,
      } as Response;
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});

    render(<App />);
    fireEvent.change(await screen.findByRole("combobox", { name: "Recent videos" }), { target: { value: video.id } });

    const transitionsHeading = await screen.findByText("Confirmed round changes");
    expect(transitionsHeading.closest("aside")).toHaveClass("library-panel");
    expect(screen.getByRole("combobox", { name: "Recent videos" })).toHaveValue(video.id);
    expect(screen.getByText("11")).toBeInTheDocument();
    expect(screen.getByText("32")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    const exportButton = await screen.findByRole("button", { name: "Download selected (7)" });
    expect(exportButton).toBeEnabled();
    expect(exportButton.closest("aside")).toHaveClass("library-panel");

    fireEvent.click(screen.getByRole("button", { name: "Show 2 more" }));

    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByText("33")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Include round 12 in export" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Download selected (7)" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Download selected (7)" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/videos/video-1/round-export"),
      expect.objectContaining({ method: "POST" }),
    ));
    const exportCall = fetchMock.mock.calls.find(([input]) => String(input).endsWith("/round-export"));
    const payload = JSON.parse(String(exportCall?.[1]?.body));
    expect(payload.game_number).toBe(1);
    expect(payload.clips.map((clip: { label: string }) => clip.label)).toEqual(["11", "12", "21", "31", "32", "41", "42"]);
  });
});

describe("round seek offset", () => {
  it("adds positive and negative offsets to the result timestamp", () => {
    expect(getSeekTimestamp(100, 2.5, 300)).toBe(102.5);
    expect(getSeekTimestamp(100, -2.5, 300)).toBe(97.5);
  });

  it("keeps an offset seek within the video duration", () => {
    expect(getSeekTimestamp(1, -5, 300)).toBe(0);
    expect(getSeekTimestamp(299, 5, 300)).toBe(300);
  });
});

describe("default round visibility", () => {
  it("features all of stage 1, every later stage start, plus 3-2 and 4-2", () => {
    const labels = ["11", "12", "21", "22", "31", "32", "33", "41", "42", "43", "51", "61", "71"];

    expect(labels.filter(isFeaturedRound)).toEqual(["11", "12", "21", "31", "32", "41", "42", "51", "61", "71"]);
  });

  it("does not feature malformed classifications", () => {
    expect(isFeaturedRound("unknown")).toBe(false);
    expect(isFeaturedRound("round_08")).toBe(false);
  });
});

describe("round export clips", () => {
  it("uses each selected transition through the next round", () => {
    const results: SampleResult[] = [0, 40, 95].map((timestamp_seconds, index) => ({
      timestamp_seconds,
      scheduled_timestamp_seconds: timestamp_seconds,
      timing_error_ms: 0,
      class_label: ["11", "12", "21"][index],
      confidence: 0.9,
    }));

    expect(buildRoundExportClips(results, new Set(["0:11", "40:12"]), 200)).toEqual([
      { label: "11", start_seconds: 0, end_seconds: 40 },
      { label: "12", start_seconds: 40, end_seconds: 95 },
    ]);
  });

  it("caps the final selected round to three minutes", () => {
    const result: SampleResult = {
      timestamp_seconds: 100,
      scheduled_timestamp_seconds: 100,
      timing_error_ms: 0,
      class_label: "71",
      confidence: 0.9,
    };

    expect(buildRoundExportClips([result], new Set(["100:71"]), 1_000)).toEqual([
      { label: "71", start_seconds: 100, end_seconds: 280 },
    ]);
  });
});


it("features every stage 1 classification in either label format", () => {
  for (let round = 1; round <= 7; round++) {
    expect(isFeaturedRound(`1${round}`)).toBe(true);
    expect(isFeaturedRound(`1-${round}`)).toBe(true);
  }
});

it("reads an automatic transcript when reopening its library video", async () => {
  const video: VideoRecord = { id: "automatic", original_name: "Automatic VOD.mp4", mime_type: "video/mp4", duration: 30, width: 32, height: 32, created_at: "2026-10-10", box: null, current_job: null, active_job: null, latest_job: null };
  const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    const payload = url.endsWith("/videos") ? [video] : url.endsWith("/videos/automatic") ? video : url.endsWith("/videos/automatic/transcription") ? {
      task_id: "automatic-text", video_id: video.id, status: "completed", transcript: "Saved automatic transcript", language: "en", error: null,
    } : url.endsWith("/replay-automation") ? {
      settings: { enabled: true, sources: ["https://www.twitch.tv/example"], daily_time: "09:00", timezone: "UTC", window_hours: 24, quality: "720p", transcribe: true }, next_run_at: null, runs: [], imports: [],
    } : url.endsWith("/playback") ? { status: "failed", error: "Test playback unavailable" } : null;
    return { ok: true, json: async () => payload } as Response;
  });
  render(<App />);
  fireEvent.change(await screen.findByLabelText("Recent videos"), { target: { value: video.id } });
  expect(await screen.findByLabelText("Raw transcript")).toHaveValue("Saved automatic transcript");
  expect(fetch.mock.calls.some(([, options]) => options?.method === "POST")).toBe(false);
});
