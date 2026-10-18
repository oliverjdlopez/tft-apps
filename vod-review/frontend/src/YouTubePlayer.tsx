import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";

export type PlayerAdapter = { seek: (time: number, play?: boolean) => void; pause: () => void; currentTime: () => number };
type Player = { seekTo: (time: number, allowSeekAhead: boolean) => void; playVideo: () => void; pauseVideo: () => void; getCurrentTime: () => number; destroy: () => void };
type YouTubeApi = { Player: new (element: HTMLElement, options: Record<string, unknown>) => Player };
declare global { interface Window { YT?: YouTubeApi; onYouTubeIframeAPIReady?: () => void } }
let apiPromise: Promise<YouTubeApi> | undefined;
function loadApi(): Promise<YouTubeApi> {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!apiPromise) apiPromise = new Promise((resolve, reject) => {
    const previous = window.onYouTubeIframeAPIReady;
    const timeout = window.setTimeout(() => { apiPromise = undefined; reject(new Error("YouTube player could not load. Check your connection or switch to Offline.")); }, 15000);
    window.onYouTubeIframeAPIReady = () => { previous?.(); window.clearTimeout(timeout); if (window.YT) resolve(window.YT); };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.onerror = () => { window.clearTimeout(timeout); apiPromise = undefined; reject(new Error("YouTube player could not load. Check your connection or switch to Offline.")); };
    document.head.appendChild(script);
  });
  return apiPromise;
}

/** Adapt source timestamps to the review timeline without reading iframe frames. */
export const YouTubePlayer = forwardRef<PlayerAdapter, { sourceId: string; start: number; duration: number; initialTime: number; onTime: (time: number) => void; onError: (message: string) => void }>(function YouTubePlayer({ sourceId, start, duration, initialTime, onTime, onError }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const player = useRef<Player | null>(null);
  const ready = useRef(false);
  const pendingSeek = useRef<{ seconds: number; play: boolean } | null>(null);
  const callbacks = useRef({ onTime, onError });
  callbacks.current = { onTime, onError };
  const time = () => Math.max(0, Math.min(duration, (ready.current ? player.current?.getCurrentTime() ?? start : start) - start));
  useImperativeHandle(ref, () => ({
    seek: (seconds, play = false) => { if (!ready.current) { pendingSeek.current = { seconds, play }; return; } player.current?.seekTo(start + Math.max(0, Math.min(duration, seconds)), true); if (play) player.current?.playVideo(); },
    pause: () => { if (ready.current) player.current?.pauseVideo(); }, currentTime: time,
  }), [start, duration]);
  useEffect(() => {
    let disposed = false;
    const target = document.createElement("iframe");
    target.title = "YouTube video player";
    target.setAttribute("referrerpolicy", "strict-origin-when-cross-origin");
    target.allow = "autoplay; encrypted-media; picture-in-picture; fullscreen";
    target.allowFullscreen = true;
    host.current?.appendChild(target);
    void loadApi().then((api) => {
      if (disposed) return;
      target.src = `https://www.youtube.com/embed/${encodeURIComponent(sourceId)}?enablejsapi=1&origin=${encodeURIComponent(window.location.origin)}&start=${Math.floor(start + initialTime)}&end=${Math.ceil(start + duration)}&playsinline=1&rel=0`;
      player.current = new api.Player(target, {
        videoId: sourceId, width: "100%", height: "100%",
        playerVars: { origin: window.location.origin, start: Math.floor(start + initialTime), end: Math.ceil(start + duration), playsinline: 1, rel: 0 },
        events: { onReady: () => { host.current?.querySelector("iframe")?.setAttribute("referrerpolicy", "strict-origin-when-cross-origin"); ready.current = true; const pending = pendingSeek.current; pendingSeek.current = null; player.current?.seekTo(start + Math.max(0, Math.min(duration, pending?.seconds ?? initialTime)), true); if (pending?.play) player.current?.playVideo(); }, onError: () => callbacks.current.onError("This video cannot be embedded or is unavailable. Switch to Offline to try downloading it.") },
      });
    }).catch((reason: Error) => { if (!disposed) callbacks.current.onError(reason.message); });
    const timer = window.setInterval(() => {
      if (!player.current || !ready.current) return;
      const actual = player.current.getCurrentTime();
      if (actual < start) player.current.seekTo(start, true);
      if (actual >= start + duration) player.current.pauseVideo();
      callbacks.current.onTime(time());
    }, 500);
    return () => { disposed = true; window.clearInterval(timer); player.current?.destroy(); player.current = null; ready.current = false; target.remove(); };
  }, [sourceId, start, duration]);
  return <div ref={host} className="youtube-player" aria-label="YouTube video player" />;
});
