import Hls from "hls.js";
import { RefObject, useEffect, useRef, useState } from "react";
import { getPlaybackStatus, playbackManifestUrl, PlaybackStatus, retryPlayback, videoContentUrl } from "./api";

const POLL_INTERVAL_MS = 1_000;

type MediaState = {
  currentTime: number;
  wasPlaying: boolean;
};

export function useOptimizedPlayback(
  videoId: string,
  videoRef: RefObject<HTMLVideoElement | null>,
): PlaybackStatus & { retry: () => Promise<void> } {
  const [playback, setPlayback] = useState<PlaybackStatus>({
    status: "preparing",
    manifest_url: null,
    error: null,
  });
  const [refreshGeneration, setRefreshGeneration] = useState(0);
  const fallbackState = useRef<MediaState | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    setPlayback({ status: "preparing", manifest_url: null, error: null });

    const refresh = async () => {
      try {
        const next = await getPlaybackStatus(videoId);
        if (cancelled) return;
        setPlayback(next);
        if (next.status === "preparing") {
          timer = window.setTimeout(refresh, POLL_INTERVAL_MS);
        }
      } catch (reason: unknown) {
        if (cancelled) return;
        setPlayback({
          status: "failed",
          manifest_url: null,
          error: reason instanceof Error ? reason.message : "Could not prepare optimized playback",
        });
      }
    };

    void refresh();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [videoId, refreshGeneration]);

  useEffect(() => {
    const element = videoRef.current;
    if (!element) return;

    const fallBackToOriginal = () => {
      fallbackState.current = {
        currentTime: Number.isFinite(element.currentTime) ? element.currentTime : 0,
        wasPlaying: !element.paused,
      };
      setPlayback({
        status: "failed", manifest_url: null,
        error: null,
      });
    };

    if (playback.status === "preparing") {
      element.removeAttribute("src");
      return;
    }

    if (playback.status === "failed" || playback.manifest_url === null) {
      const fallbackUrl = videoContentUrl(videoId);
      const absoluteFallbackUrl = new URL(fallbackUrl, window.location.href).href;
      const onError = () => setPlayback({
        status: "failed", manifest_url: null,
        error: "The original video could not be played. Check that the backend is running, then retry playback.",
      });
      element.addEventListener("error", onError);
      const onCanPlay = () => setPlayback((current) => ({ ...current, error: null }));
      element.addEventListener("canplay", onCanPlay);
      if (element.src === absoluteFallbackUrl) return () => {
        element.removeEventListener("error", onError);
        element.removeEventListener("canplay", onCanPlay);
      };

      const savedState = fallbackState.current;
      fallbackState.current = null;
      element.src = fallbackUrl;
      const restore = () => {
        if (savedState !== null) {
          const maximumTime = Number.isFinite(element.duration) ? element.duration : savedState.currentTime;
          element.currentTime = Math.max(0, Math.min(maximumTime, savedState.currentTime));
          if (savedState.wasPlaying) void element.play().catch(() => undefined);
        }
      };
      element.addEventListener("loadedmetadata", restore, { once: true });
      return () => {
        element.removeEventListener("error", onError);
        element.removeEventListener("canplay", onCanPlay);
        element.removeEventListener("loadedmetadata", restore);
      };
    }

    const manifestUrl = playbackManifestUrl(playback.manifest_url);
    if (element.canPlayType("application/vnd.apple.mpegurl")) {
      element.addEventListener("error", fallBackToOriginal);
      element.src = manifestUrl;
      return () => element.removeEventListener("error", fallBackToOriginal);
    }

    if (!Hls.isSupported()) {
      fallBackToOriginal();
      return;
    }

    const hls = new Hls({
      backBufferLength: 30,
      maxBufferLength: 30,
    });
    hls.loadSource(manifestUrl);
    hls.attachMedia(element);
    hls.on(Hls.Events.ERROR, (_event, data) => {
      if (!data.fatal) return;
      fallBackToOriginal();
    });
    return () => hls.destroy();
  }, [playback.status, playback.manifest_url, videoId, videoRef]);

  const retry = async () => {
    setPlayback({ status: "preparing", manifest_url: null, error: null });
    await retryPlayback(videoId);
    setRefreshGeneration((current) => current + 1);
  };

  return { ...playback, retry };
}
