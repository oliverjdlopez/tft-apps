import { useEffect, useMemo, useRef, useState } from "react";
import Hls from "hls.js";
import { BookOpen, Film, RefreshCw, Search, ListVideo, Play } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { API_BASE } from "./api";
import { groupRoundTransitions } from "./App";
import { YouTubePlayer, type PlayerAdapter } from "./YouTubePlayer";
import { TwitchPlayer } from "./TwitchPlayer";
import { getViewingMedia, listViewingMedia, type ViewingDetail, type ViewingEntry } from "./viewing-api";
import "./viewing-library.css";

function timestamp(seconds: number) {
  const value = Math.floor(Math.max(0, seconds));
  const hours = Math.floor(value / 3600);
  return `${hours ? `${hours}:` : ""}${String(Math.floor(value / 60) % 60).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
}

function Availability({ entry }: { entry: ViewingEntry }) {
  return <span className="viewing-badges">
    {entry.has_transcript && <Badge variant="secondary"><BookOpen size={12} /> Transcript</Badge>}
    {entry.has_transitions && <Badge variant="secondary"><ListVideo size={12} /> Game / rounds</Badge>}
  </span>;
}

/** Browse only existing content, retaining selection as the desktop tab hides. */
export default function ViewingLibrary() {
  const [entries, setEntries] = useState<ViewingEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [generation, refresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    void listViewingMedia(controller.signal).then((items) => {
      if (controller.signal.aborted) return;
      setEntries(items);
      setSelected((id) => items.some((item) => item.id === id) ? id : items[0]?.id ?? null);
    }).catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [generation]);
  const visible = entries.filter((entry) => `${entry.name} ${entry.source}`.toLowerCase().includes(search.toLowerCase()));
  return <main className="viewing-library">
    <aside className="viewing-sidebar" aria-label="Viewing library">
      <header><span className="viewing-kicker">YOUR LIBRARY</span><h1>Watch &amp; Read</h1><p>Videos with saved transcripts or round transitions.</p></header>
      <div className="viewing-search"><Search size={16} /><Input aria-label="Search videos" placeholder="Search your videos…" value={search} onChange={(event) => setSearch(event.target.value)} /></div>
      <div className="viewing-library-tools"><span>{entries.length} {entries.length === 1 ? "video" : "videos"}</span><Button variant="ghost" size="sm" disabled={loading} onClick={() => refresh((value) => value + 1)}><RefreshCw size={14} /> Refresh</Button></div>
      {loading && <p role="status">Loading library…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && entries.length === 0 && <p className="viewing-empty">No videos with saved transcripts or round transitions yet.</p>}
      {!loading && entries.length > 0 && !visible.length && <p role="status">No videos match your search.</p>}
      <ul className="viewing-items" aria-label="Available videos">{visible.map((entry) => <li key={entry.id}>
        <button className="viewing-item" aria-pressed={selected === entry.id} onClick={() => setSelected(entry.id)}>
          <span className="viewing-item-title"><Film size={17} /><strong>{entry.name}</strong></span>
          <span className="viewing-item-meta">{entry.local_available ? "Offline" : entry.source_id ? "Online" : "Video unavailable"}{entry.duration > 0 ? ` · ${timestamp(entry.duration)}` : ""}</span>
          <Availability entry={entry} />
        </button>
      </li>)}</ul>
    </aside>
    <section className="viewing-main" aria-label="Selected video">
      {selected ? <EntryReader key={selected} id={selected} generation={generation} /> : <div className="viewing-placeholder"><Film size={38} /><h2>Your videos, ready to explore</h2><p>Choose a video to watch or read its saved transcript.</p></div>}
    </section>
  </main>;
}

function EntryReader({ id, generation }: { id: string; generation: number }) {
  const [entry, setEntry] = useState<ViewingDetail | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [mode, setMode] = useState<"video" | "transcript">("video");
  const [time, setTime] = useState(0);
  const [query, setQuery] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void getViewingMedia(id, controller.signal).then((item) => {
      if (!controller.signal.aborted) setEntry(item);
    }).catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [id, generation, retry]);
  if (error) return <div className="viewing-placeholder"><p role="alert">{error}</p><Button variant="outline" onClick={() => setRetry((value) => value + 1)}>Retry</Button></div>;
  if (!entry) return <p role="status">Loading saved content…</p>;
  const transcript = entry.transcript;
  const segments = transcript?.segments;
  const matches = segments?.filter((segment) => segment.text.toLowerCase().includes(query.toLowerCase()));
  return <>
    <header className="viewing-detail-header"><span className="viewing-kicker">{entry.local_available ? "OFFLINE VIDEO" : entry.source_id ? "ONLINE VIDEO" : "VIDEO UNAVAILABLE"}</span><h2>{entry.name}</h2><p>{entry.source}</p><Availability entry={entry} /></header>
    <div className="viewing-modes" role="group" aria-label="Content view">
      <Button variant={mode === "video" ? "secondary" : "ghost"} aria-pressed={mode === "video"} onClick={() => setMode("video")}><Film size={16} /> Video{entry.has_transitions ? " & rounds" : ""}</Button>
      <Button variant={mode === "transcript" ? "secondary" : "ghost"} aria-pressed={mode === "transcript"} disabled={!entry.has_transcript} onClick={() => setMode("transcript")}><BookOpen size={16} /> Transcript</Button>
      {!entry.has_transcript && <span>No saved transcript</span>}
    </div>
    {mode === "video" ? <VideoReader entry={entry} time={time} onTime={setTime} /> : <section className="viewing-transcript" aria-label="Saved transcript">
      <div className="viewing-transcript-heading"><h3>Transcript</h3>{transcript?.language && <Badge variant="outline">{transcript.language}</Badge>}</div>
      {entry.transcript_error && <p role="alert">{entry.transcript_error}</p>}
      {!!segments?.length && <Input aria-label="Search transcript" placeholder="Find in transcript…" value={query} onChange={(event) => setQuery(event.target.value)} />}
      {segments?.length ? <div className="viewing-segments">{matches?.length ? matches.map((segment, index) => <div className="viewing-segment" key={`${segment.start}-${index}`}>
        <Button variant="ghost" size="sm" aria-label={`Watch from ${timestamp(segment.start)}`} onClick={() => { setTime(segment.start); setMode("video"); }}>{timestamp(segment.start)}</Button><p>{segment.text}</p>
      </div>) : <p role="status">No transcript passages match.</p>}</div> : <p className="viewing-prose">{transcript?.transcript || (!entry.transcript_error ? "This transcript contains no speech." : "")}</p>}
    </section>}
  </>;
}

function VideoReader({ entry, time, onTime }: { entry: ViewingDetail; time: number; onTime: (time: number) => void }) {
  const video = useRef<HTMLVideoElement>(null);
  const online = useRef<PlayerAdapter>(null);
  const initial = useRef(time);
  const [error, setError] = useState("");
  const [playback, setPlayback] = useState(entry.local_available ? "offline" : "online");
  const games = useMemo(() => groupRoundTransitions(entry.transitions), [entry.transitions]);
  const currentGame = games.reduce((index, item, candidate) => time >= item.results[0].timestamp_seconds ? candidate : index, 0);
  const [gameIndex, setGameIndex] = useState(currentGame);
  useEffect(() => setGameIndex(currentGame), [currentGame]);
  const game = games[Math.min(gameIndex, games.length - 1)];
  useEffect(() => {
    const element = video.current;
    setError("");
    if (!element || playback !== "offline") return;
    const fallback = () => { if (entry.content_url) element.src = `${API_BASE}${entry.content_url}`; };
    if (!entry.manifest_url) { fallback(); return; }
    const manifest = `${API_BASE}${entry.manifest_url}`;
    if (element.canPlayType("application/vnd.apple.mpegurl")) { element.src = manifest; return; }
    if (!Hls.isSupported()) { fallback(); return; }
    const hls = new Hls();
    hls.loadSource(manifest); hls.attachMedia(element);
    hls.on(Hls.Events.ERROR, (_event, data) => { if (data.fatal) { hls.destroy(); fallback(); } });
    return () => hls.destroy();
  }, [entry.content_url, entry.manifest_url, playback]);
  useEffect(() => {
    const pause = () => { if (document.hidden) { video.current?.pause(); online.current?.pause(); } };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, []);
  const seek = (seconds: number) => {
    onTime(seconds);
    if (video.current) video.current.currentTime = seconds;
    online.current?.seek(seconds);
  };
  const Player = entry.source_id?.startsWith("twitch:") ? TwitchPlayer : YouTubePlayer;
  return <div className="viewing-video-layout">
    <section className="viewing-player-section" aria-label="Video playback">
      {entry.local_available && entry.source_id && <div className="viewing-playback-choice"><label>Playback <select aria-label="Playback source" value={playback} onChange={(event) => { initial.current = time; setError(""); setPlayback(event.target.value); }}><option value="offline">Offline copy</option><option value="online">Online source</option></select></label></div>}
      <div className="viewing-player">
        {playback === "offline" && entry.content_url ? <video ref={video} controls playsInline preload="metadata" aria-label={entry.name} onLoadedMetadata={(event) => { event.currentTarget.currentTime = initial.current; }} onTimeUpdate={(event) => onTime(event.currentTarget.currentTime)} onError={() => setError("This saved video could not be played. Its file may be missing or its format unsupported.")} />
          : entry.source_id ? <Player ref={online} sourceId={entry.source_id} start={entry.start} duration={entry.duration} initialTime={initial.current} onTime={onTime} onError={() => setError("The online video is unavailable or cannot be embedded.")} />
            : <p>Video file is unavailable. Its saved transcript is still accessible.</p>}
      </div>
      {error && <p role="alert">{error}</p>}
      <p className="viewing-playback-note">{timestamp(time)}{entry.duration > 0 ? ` / ${timestamp(entry.duration)}` : ""}{entry.has_transitions ? " · Select a round to jump to its saved timestamp." : " · No saved game or round transitions."}</p>
    </section>
    {entry.has_transitions && <section className="viewing-rounds" aria-label="Game and round transitions">
      <header><ListVideo size={18} /><h3>Game &amp; rounds</h3></header>
      <label>Game <select aria-label="Select game" value={Math.min(gameIndex, games.length - 1)} onChange={(event) => { const index = Number(event.target.value); setGameIndex(index); seek(games[index].results[0].timestamp_seconds); }}>{games.map((item, index) => <option key={item.number} value={index}>Game {item.number} · {item.results.length} rounds</option>)}</select></label>
      <div className="viewing-round-list">{game?.results.map((result, index) => {
        const active = time >= result.timestamp_seconds && time < (game.results[index + 1]?.timestamp_seconds ?? games[gameIndex + 1]?.results[0]?.timestamp_seconds ?? Infinity);
        return <button key={`${result.timestamp_seconds}-${index}`} aria-current={active ? "true" : undefined} onClick={() => seek(result.timestamp_seconds)}><span><Play size={12} /> Round {result.class_label.replace(/^(\d)(\d)$/, "$1-$2")}</span><time>{timestamp(result.timestamp_seconds)}</time></button>;
      })}</div>
    </section>}
  </div>;
}
