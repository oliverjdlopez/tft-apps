import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ViewingLibrary from "./ViewingLibrary";
import { getViewingMedia, listViewingMedia, type ViewingDetail } from "./viewing-api";

vi.mock("./viewing-api", () => ({ listViewingMedia: vi.fn(), getViewingMedia: vi.fn() }));
vi.mock("./YouTubePlayer", () => ({ YouTubePlayer: ({ start, initialTime }: { start: number; initialTime: number }) => <div data-testid="online-player">Source {start}; position {initialTime}</div> }));
vi.mock("./TwitchPlayer", () => ({ TwitchPlayer: () => <div>Twitch video</div> }));
const fixture = (id: string, overrides: Partial<ViewingDetail> = {}): ViewingDetail => ({
  id, name: `${id} tournament`, source: "Saved video", duration: 600, source_id: null, start: 0,
  local_available: true, video_id: id, content_url: `/api/viewing-library/${id}/content`,
  has_transcript: true, has_transitions: true, manifest_url: null, transcript_error: null,
  transcript: { transcript: "Saved speech", language: "en", segments: [{ start: 7, end: 9, text: "Saved speech" }] },
  transitions: [{ timestamp_seconds: 10.125, scheduled_timestamp_seconds: 10, timing_error_ms: 125, class_label: "21", confidence: .9 }], ...overrides,
});
beforeEach(() => {
  vi.mocked(listViewingMedia).mockResolvedValue([fixture("first"), fixture("second", { has_transcript: false, transcript: null })]);
  vi.mocked(getViewingMedia).mockImplementation(async (id) => fixture(id, id === "second" ? { has_transcript: false, transcript: null } : {}));
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

describe("Watch & Read", () => {
  it("opens saved video and seeks actual round PTS, with no processing controls", async () => {
    render(<ViewingLibrary />);
    const media = await screen.findByLabelText("first tournament");
    fireEvent.click(screen.getByRole("button", { name: /Round 2-1/ }));
    expect((media as HTMLVideoElement).currentTime).toBe(10.125);
    expect(screen.getByRole("region", { name: "Game and round transitions" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /transcribe|distill|analyze|discover|download|upload/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Transcript" }));
    expect(screen.queryByRole("region", { name: "Game and round transitions" })).not.toBeInTheDocument();
    expect(screen.getByText("Saved speech")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search transcript" }), { target: { value: "missing" } });
    expect(screen.getByText("No transcript passages match.")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search transcript" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Watch from 00:07" }));
    const resumed = screen.getByLabelText("first tournament") as HTMLVideoElement;
    fireEvent.loadedMetadata(resumed);
    expect(resumed.currentTime).toBe(7);
  });

  it("filters the left library and disables unavailable transcript view", async () => {
    render(<ViewingLibrary />);
    await screen.findByLabelText("first tournament");
    fireEvent.change(screen.getByRole("textbox", { name: "Search videos" }), { target: { value: "second" } });
    const list = screen.getByRole("list", { name: "Available videos" });
    expect(within(list).queryByText("first tournament")).not.toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button"));
    await screen.findByLabelText("second tournament");
    expect(screen.getByRole("button", { name: "Transcript" })).toBeDisabled();
  });

  it("keeps online source offsets when jumping from transcript to video", async () => {
    const remote = fixture("remote", { source_id: "youtube-id", start: 300, local_available: false, content_url: null });
    vi.mocked(listViewingMedia).mockResolvedValue([remote]);
    vi.mocked(getViewingMedia).mockResolvedValue(remote);
    render(<ViewingLibrary />);
    expect(await screen.findByTestId("online-player")).toHaveTextContent("Source 300; position 0");
    fireEvent.click(screen.getByRole("button", { name: "Transcript" }));
    fireEvent.click(screen.getByRole("button", { name: "Watch from 00:07" }));
    expect(screen.getByTestId("online-player")).toHaveTextContent("Source 300; position 7");
  });

  it("ignores an old selection response and pauses when the desktop tab hides", async () => {
    let finishFirst!: (entry: ViewingDetail) => void;
    vi.mocked(getViewingMedia).mockImplementation((id) => id === "first" ? new Promise((resolve) => { finishFirst = resolve; }) : Promise.resolve(fixture(id)));
    render(<ViewingLibrary />);
    fireEvent.click(await screen.findByRole("button", { name: /second tournament/ }));
    await screen.findByLabelText("second tournament");
    finishFirst(fixture("first"));
    await waitFor(() => expect(screen.queryByLabelText("first tournament")).not.toBeInTheDocument());
    vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    fireEvent(document, new Event("visibilitychange"));
    expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it("shows recoverable errors and an honest empty state", async () => {
    vi.mocked(listViewingMedia).mockRejectedValueOnce(new Error("Storage is unavailable"));
    render(<ViewingLibrary />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage is unavailable");
    vi.mocked(listViewingMedia).mockResolvedValue([]);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText("No videos with saved transcripts or round transitions yet.")).toBeInTheDocument();
  });

  it("keeps text-only transcripts readable without inventing timestamps", async () => {
    vi.mocked(getViewingMedia).mockResolvedValue(fixture("first", { transcript: { transcript: "Legacy transcript\nSecond line", segments: null, language: null }, has_transitions: false }));
    render(<ViewingLibrary />);
    await screen.findByLabelText("first tournament");
    fireEvent.click(screen.getByRole("button", { name: "Transcript" }));
    expect(screen.getByText(/Legacy transcript/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Watch from/ })).not.toBeInTheDocument();
  });
});
