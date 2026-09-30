import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useRef } from "react";

const hlsMock = vi.hoisted(() => ({
  instances: [] as Array<{
    handlers: Map<string, (event: string, data: { fatal: boolean }) => void>;
    destroy: ReturnType<typeof vi.fn>;
  }>,
}));

vi.mock("hls.js", () => {
  class MockHls {
    static Events = { ERROR: "hlsError" };
    static isSupported = () => true;
    handlers = new Map<string, (event: string, data: { fatal: boolean }) => void>();
    destroy = vi.fn();

    constructor() {
      hlsMock.instances.push(this);
    }

    loadSource() {}
    attachMedia() {}
    on(event: string, handler: (event: string, data: { fatal: boolean }) => void) {
      this.handlers.set(event, handler);
    }
  }

  return { default: MockHls };
});

vi.mock("./api", () => ({
  getPlaybackStatus: vi.fn(async () => ({
    status: "ready",
    manifest_url: "/api/videos/video-id/playback/index.m3u8",
    error: null,
  })),
  playbackManifestUrl: (path: string) => `http://localhost:8000${path}`,
  retryPlayback: vi.fn(),
  videoContentUrl: (id: string) => `http://localhost:8000/api/videos/${id}/content`,
}));

import { useOptimizedPlayback } from "./useOptimizedPlayback";

function PlaybackHarness() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const playback = useOptimizedPlayback("video-id", videoRef);
  return <><video ref={videoRef} /><span>{playback.status}</span>{playback.error && <span role="alert">{playback.error}</span>}</>;
}

afterEach(() => {
  cleanup();
  hlsMock.instances.length = 0;
  vi.restoreAllMocks();
});

describe("useOptimizedPlayback", () => {
  it("recovers native HLS errors without leaving the player on a broken manifest", async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('probably');
    render(<PlaybackHarness />);
    await screen.findByText('ready');
    const video = document.querySelector('video')!;
    expect(video.src).toContain('index.m3u8');
    video.currentTime = 12;
    Object.defineProperty(video, 'paused', { configurable: true, get: () => false });
    const play = vi.spyOn(video, 'play').mockResolvedValue();
    fireEvent.error(video);
    await screen.findByText('failed');
    expect(video.src).toContain('/content');
    fireEvent.loadedMetadata(video);
    expect(video.currentTime).toBe(12);
    expect(play).toHaveBeenCalledOnce();
    expect(hlsMock.instances).toHaveLength(0);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    fireEvent.error(video);
    expect(await screen.findByRole('alert')).toHaveTextContent('original video could not be played');
    fireEvent.canPlay(video);
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
  it("restores active playback when HLS falls back to the original video", async () => {
    render(<PlaybackHarness />);

    await screen.findByText("ready");
    await waitFor(() => expect(hlsMock.instances).toHaveLength(1));
    const video = document.querySelector("video")!;
    video.currentTime = 42;
    Object.defineProperty(video, "duration", { configurable: true, value: 100 });
    Object.defineProperty(video, "paused", { configurable: true, get: () => false });
    const play = vi.spyOn(video, "play").mockResolvedValue();

    act(() => {
      hlsMock.instances[0].handlers.get("hlsError")?.("hlsError", { fatal: true });
    });

    await screen.findByText("failed");
    expect(video.src).toBe("http://localhost:8000/api/videos/video-id/content");
    video.currentTime = 0;
    fireEvent.loadedMetadata(video);

    expect(video.currentTime).toBe(42);
    expect(play).toHaveBeenCalledOnce();
  });
});
