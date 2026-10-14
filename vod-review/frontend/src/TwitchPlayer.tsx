import { forwardRef, useEffect, useId, useImperativeHandle, useRef } from "react";
import type { PlayerAdapter } from "./YouTubePlayer";

type Player = { seek: (time: number) => void; play: () => void; pause: () => void; getCurrentTime: () => number; getDuration: () => number; addEventListener: (event: string, callback: () => void) => void; removeEventListener: (event: string, callback: () => void) => void };
type TwitchApi = { Player: { new (id: string, options: Record<string, unknown>): Player; READY: string } };
declare global { interface Window { Twitch?: TwitchApi } }
let apiPromise: Promise<TwitchApi> | undefined;
function loadApi(): Promise<TwitchApi> {
  if (window.Twitch?.Player) return Promise.resolve(window.Twitch);
  if (!apiPromise) apiPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    const fail = () => { apiPromise = undefined; script.remove(); reject(new Error("Twitch player could not load. Check your connection or switch to Offline.")); };
    const timeout = window.setTimeout(fail, 15000);
    script.src = "https://player.twitch.tv/js/embed/v1.js";
    script.onload = () => { window.clearTimeout(timeout); if (window.Twitch?.Player) resolve(window.Twitch); else fail(); };
    script.onerror = () => { window.clearTimeout(timeout); fail(); };
    document.head.appendChild(script);
  });
  return apiPromise;
}

/** Map Twitch VOD playback and seeks onto the saved review range. */
export const TwitchPlayer = forwardRef<PlayerAdapter, { sourceId: string; start: number; duration: number; initialTime: number; onTime: (time: number) => void; onError: (message: string) => void }>(function TwitchPlayer({ sourceId, start, duration, initialTime, onTime, onError }, ref) {
  const host = useRef<HTMLDivElement>(null);
  const id = `twitch-${useId().replace(/:/g, "")}`;
  const player = useRef<Player | null>(null);
  const ready = useRef(false);
  const pendingSeek = useRef<number | null>(null);
  const lastSeekAttempt = useRef(0);
  const pendingPlay = useRef(false);
  const callbacks = useRef({ onTime, onError });
  callbacks.current = { onTime, onError };
  const time = () => Math.max(0, Math.min(duration, (ready.current ? player.current?.getCurrentTime() ?? start : start) - start));
  const seek = (seconds: number) => {
    pendingSeek.current = start + Math.max(0, Math.min(duration, seconds));
    if (ready.current && (player.current?.getDuration() ?? 0) > 0) {
      player.current?.seek(pendingSeek.current);
      lastSeekAttempt.current = Date.now();
    }
  };
  useImperativeHandle(ref, () => ({
    seek: (seconds, play = false) => { seek(seconds); if (play) { if (ready.current) player.current?.play(); else pendingPlay.current = true; } },
    pause: () => { if (ready.current) player.current?.pause(); }, currentTime: time,
  }), [start, duration]);
  useEffect(() => {
    let disposed = false;
    let instance: Player | null = null;
    let readyTimer: number | undefined;
    const onReady = () => { if (disposed) return; window.clearTimeout(readyTimer); ready.current = true; seek(pendingSeek.current === null ? initialTime : pendingSeek.current - start); if (pendingPlay.current) { instance?.play(); pendingPlay.current = false; } };
    void loadApi().then((api) => {
      if (disposed) return;
      instance = new api.Player(id, { video: sourceId.replace(/^twitch:/, ""), parent: [window.location.hostname], width: "100%", height: "100%", autoplay: false });
      player.current = instance;
      instance.addEventListener(api.Player.READY, onReady);
      readyTimer = window.setTimeout(() => callbacks.current.onError("Twitch playback is unavailable. Switch to Offline to try downloading this VOD."), 20000);
    }).catch((reason: Error) => { if (!disposed) callbacks.current.onError(reason.message); });
    const timer = window.setInterval(() => {
      if (!ready.current || !instance) return;
      // READY can precede VOD metadata; preserve requested seeks until its
      // duration is available instead of dropping them during player startup.
      const actual = instance.getCurrentTime();
      if (pendingSeek.current !== null) {
        if (Math.abs(actual - pendingSeek.current) < 1) pendingSeek.current = null;
        else if (instance.getDuration() > 0 && Date.now() - lastSeekAttempt.current >= 5000) {
          // Twitch may ignore seeks while a preroll advertisement is active.
          // Retain the user's destination and retry once playback accepts it.
          instance.seek(pendingSeek.current);
          lastSeekAttempt.current = Date.now();
        }
      }
      if (pendingSeek.current === null && actual < start) instance.seek(start);
      if (actual >= start + duration) instance.pause();
      callbacks.current.onTime(time());
    }, 500);
    return () => { disposed = true; window.clearInterval(timer); window.clearTimeout(readyTimer); if (instance) { instance.pause(); if (window.Twitch) instance.removeEventListener(window.Twitch.Player.READY, onReady); } player.current = null; ready.current = false; pendingSeek.current = null; pendingPlay.current = false; host.current?.replaceChildren(); };
  }, [id, sourceId, start, duration]);
  return <div ref={host} id={id} className="youtube-player" aria-label="Twitch video player" />;
});
