import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import type { TranscriptionTask } from "./api";
import { useTranscriptTasks, type Evidence, type MomentsOutput } from "./useTranscriptTasks";
import "./TranscriptTools.css";

type Tab = "moments" | "notes" | "transcript";
type Props = { title: string; transcription: TranscriptionTask | null; videoId?: string; online?: boolean; transcribing?: boolean; onTranscribe?: () => void; onSeek?: (seconds: number, play: boolean) => void; focusTranscript?: number };
const actions = [{ name: "transcription_pipeline", label: "Distill transcript", tab: "notes" as Tab }, { name: "find_key_moments", label: "Find key moments", tab: "moments" as Tab }];
const stamp = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

function savedTab(key: string): Tab {
  try { const value = localStorage.getItem(key); if (value === "moments" || value === "notes" || value === "transcript") return value; } catch { /* Storage is optional. */ }
  return "transcript";
}

/** Reusable transcript workspace; audio-only callers omit the playback callback. */
export function TranscriptTools({ title, transcription, videoId, online, transcribing, onTranscribe, onSeek, focusTranscript = 0 }: Props) {
  const tools = useTranscriptTasks(transcription?.task_id, videoId);
  const storageKey = `vod-transcript-tab:${videoId ?? transcription?.task_id ?? "audio"}`;
  const [tab, setTab] = useState<Tab>(() => savedTab(storageKey));
  const [highlight, setHighlight] = useState<Evidence | null>(null);
  const [copyError, setCopyError] = useState("");
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => { setTab(savedTab(storageKey)); setHighlight(null); }, [storageKey]);
  useEffect(() => { if (focusTranscript) setTab("transcript"); }, [focusTranscript]);
  useEffect(() => { try { localStorage.setItem(storageKey, tab); } catch { /* Backend results do not depend on storage. */ } }, [storageKey, tab]);
  useEffect(() => { if (tab === "transcript" && highlight) content.current?.querySelector("[data-highlighted=true]")?.scrollIntoView?.({ block: "nearest" }); }, [tab, highlight]);
  const source = tools.source;
  const completed = transcription?.status === "completed";
  const speech = completed && Boolean((source?.transcript ?? transcription?.transcript)?.trim());
  const timed = Boolean(source?.segments?.length);
  const pending = transcribing || transcription?.status === "queued" || transcription?.status === "running";
  const output = (name: string) => tools.tasks.find(task => task.name === name)?.successful_run?.output;
  const moments = output("find_key_moments") as MomentsOutput | undefined;
  const notes = output("transcription_pipeline");
  const segments = source?.segments;
  const firstHighlight = segments?.findIndex(s => s.id === highlight?.start_segment_id) ?? -1;
  const lastHighlight = segments?.findIndex(s => s.id === highlight?.end_segment_id) ?? -1;
  const timestamp = (seconds: number, label?: string) => onSeek
    ? <button type="button" className="transcript-timestamp" onClick={() => onSeek(seconds, true)}>{stamp(seconds)}{label ? ` · ${label}` : ""}</button>
    : <span>{stamp(seconds)}{label ? ` · ${label}` : ""}</span>;
  const copyOriginal = async () => {
    try { await navigator.clipboard.writeText(source?.transcript ?? transcription?.transcript ?? ""); setCopyError(""); }
    catch { setCopyError("Could not copy the transcript"); }
  };
  return <section className="transcript-tools" aria-label="Transcript tools">
    <h3>{videoId ? title : source?.title ?? title}</h3>
    <div className="transcript-actions">{actions.map(action => {
      const state = tools.tasks.find(task => task.name === action.name);
      const definition = tools.definitions.find(task => task.name === action.name);
      const active = Boolean(state?.active_run || tools.starting[action.name]);
      const failed = state?.latest_run?.status === "failed";
      return <div key={action.name}>
        <button type="button" disabled={!speech || !source || !definition?.available || active || (action.name === "find_key_moments" && !timed)} onClick={() => { setTab(action.tab); void tools.start(action.name, Boolean(state?.successful_run || failed)); }}>{active ? `${action.label}…` : failed ? `Retry ${action.label.toLowerCase()}` : action.label}</button>
        <p role="status">{active ? (state?.active_run?.status ?? "Starting") : failed ? `${state?.successful_run ? "Rerun failed. " : ""}${state?.latest_run?.error}` : state?.successful_run ? "Saved result" : ""}</p>
        {tools.errors[action.name] && <p role="alert">{tools.errors[action.name]}</p>}
        {definition && !definition.available && <p>{definition.reason}</p>}
      </div>;
    })}</div>
    {!transcription && <p>{online ? "Generating a transcript requires an Offline copy." : "Transcribe this source to use transcript tools."}</p>}
    {pending && <p role="status">Recognizing speech… {Math.round(transcription?.progress ?? 0)}%</p>}
    {completed && !speech && <p>No speech was detected</p>}
    {speech && source && !timed && <p>{videoId ? "Timing is unavailable. Retranscribe this video to find key moments." : "Timing is unavailable. Reimport the audio source to obtain timing."}</p>}
    {onTranscribe && !online && !pending && (!transcription || transcription.status === "failed" || (speech && source?.segments == null)) && <button type="button" onClick={onTranscribe}>{speech ? "Retranscribe video for timing" : "Transcribe video"}</button>}
    {transcription?.status === "failed" && <p role="alert">{transcription.error}</p>}
    {tools.error && <p role="alert">{tools.error}</p>}
    <div role="tablist" aria-label="Transcript views">{([['moments', 'Key moments'], ['notes', 'Distilled notes'], ['transcript', 'Transcript']] as [Tab, string][]).map(([value, label]) => <button key={value} id={`tab-${videoId ?? "audio"}-${value}`} type="button" role="tab" aria-selected={tab === value} aria-controls={`panel-${videoId ?? "audio"}`} onClick={() => setTab(value)} onKeyDown={event => {
      const order: Tab[] = ["moments", "notes", "transcript"];
      const index = order.indexOf(value);
      const next = event.key === "ArrowRight" ? (index + 1) % 3 : event.key === "ArrowLeft" ? (index + 2) % 3 : event.key === "Home" ? 0 : event.key === "End" ? 2 : null;
      if (next !== null) { event.preventDefault(); setTab(order[next]); document.getElementById(`tab-${videoId ?? "audio"}-${order[next]}`)?.focus(); }
    }}>{label}</button>)}</div>
    <div ref={content} id={`panel-${videoId ?? "audio"}`} className="transcript-content" role="tabpanel" aria-labelledby={`tab-${videoId ?? "audio"}-${tab}`} tabIndex={0}>
      {tab === "moments" && (moments ? (moments.moments.length ? moments.moments.map((moment, index) => <article className="moment-card" key={index}>
        <h4>{timestamp(moment.evidence[0].start_seconds, moment.title)}</h4><p>{moment.explanation}</p>
        {moment.evidence.map((evidence, range) => <div key={range}>
          {moment.evidence.length > 1 && <p>{timestamp(evidence.start_seconds)} – {stamp(evidence.end_seconds)}</p>}
          <details><summary>Source excerpt</summary><blockquote>{evidence.excerpt}</blockquote></details>
          <button type="button" onClick={() => { setHighlight(evidence); setTab("transcript"); }}>Show in transcript{moment.evidence.length > 1 ? ` (${range + 1})` : ""}</button>
        </div>)}
      </article>) : <p>No critical moments were identified in this transcript.</p>) : <p>Choose Find key moments to examine consequential passages.</p>)}
      {tab === "notes" && (typeof notes === "string" ? <div className="distilled-markdown"><Markdown skipHtml>{notes}</Markdown></div> : <p>Choose Distill transcript to create source-grounded notes.</p>)}
      {tab === "transcript" && completed && <>
        {source?.language && <p>Detected language: {source.language}</p>}
        {segments?.map((segment, index) => <div className="transcript-segment" data-highlighted={firstHighlight >= 0 && index >= firstHighlight && index <= lastHighlight} key={segment.id}>{timestamp(segment.start)}<span>{segment.text}</span></div>)}
        <details open={!segments?.length}><summary>Original plain transcript</summary>
          <button type="button" disabled={!speech} onClick={() => void copyOriginal()}>Copy original transcript</button>
          {copyError && <p role="alert">{copyError}</p>}
          <textarea aria-label="Transcript text" value={source?.transcript ?? transcription?.transcript ?? ""} readOnly rows={14} />
        </details>
      </>}
    </div>
  </section>;
}
