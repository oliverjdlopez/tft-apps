import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ListVideo, LoaderCircle } from "lucide-react";
import { Input as UiInput } from "@/components/ui/input";
import type { VideoRecord } from "./api";

export type InProgressItem = {
  id: string;
  title: string;
  stage: string;
  progress: number | null;
  videoId: string | null;
};

export type VideoStatus = { label: string; tone: "new" | "ready" | "busy" | "failed" | "idle" };

export function videoStatus(video: VideoRecord, unseen: boolean): VideoStatus {
  const active = video.active_job;
  if (active && (active.status === "queued" || active.status === "running")) return { label: "Analyzing", tone: "busy" };
  if (video.latest_job?.status === "failed") return { label: "Analysis failed", tone: "failed" };
  if (unseen) return { label: "New", tone: "new" };
  if (video.current_job?.status === "completed") return { label: "Analyzed", tone: "ready" };
  if (!video.box) return { label: "Needs region", tone: "idle" };
  return { label: "Not analyzed", tone: "idle" };
}

function formatLength(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor(whole / 60) % 60;
  const rest = String(whole % 60).padStart(2, "0");
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${rest}` : `${minutes}:${rest}`;
}

function formatAdded(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const hours = (Date.now() - date.getTime()) / 3_600_000;
  if (hours >= 0 && hours < 1) return "just now";
  if (hours >= 0 && hours < 24) return `${Math.floor(hours)}h ago`;
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

/** Header video picker: the current review plus a dropdown of ready and in-progress replays. */
export function ReplaySwitcher({ videos, selected, unseen, inProgress, loading, open, onOpenChange, onSelect, onFindReplays, findingReplays, extraAction }: {
  videos: VideoRecord[];
  selected: VideoRecord | null;
  unseen: ReadonlySet<string>;
  inProgress: InProgressItem[];
  loading: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (id: string) => void;
  onFindReplays: () => void;
  findingReplays: boolean;
  extraAction?: ReactNode;
}) {
  const [filter, setFilter] = useState("");
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => { if (!root.current?.contains(event.target as Node)) onOpenChange(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, onOpenChange]);

  useEffect(() => { if (!open) setFilter(""); }, [open]);

  const visible = useMemo(() => {
    const query = filter.trim().toLowerCase();
    return query ? videos.filter((video) => video.original_name.toLowerCase().includes(query)) : videos;
  }, [videos, filter]);

  const unseenCount = videos.filter((video) => unseen.has(video.id)).length;
  const summary = [unseenCount ? `${unseenCount} new` : "", inProgress.length ? `${inProgress.length} processing` : ""].filter(Boolean).join(" · ");
  const selectedStatus = selected ? videoStatus(selected, false) : null;

  return <div className="replay-switcher" ref={root} onKeyDown={(event) => { if (event.key === "Escape" && open) { event.stopPropagation(); onOpenChange(false); } }}>
    <button type="button" className="replay-switcher-trigger" aria-haspopup="dialog" aria-expanded={open} aria-label={selected ? `Switch replay, current: ${selected.original_name}` : "Choose a replay"} onClick={() => onOpenChange(!open)}>
      <span className="replay-switcher-copy">
        <span className="replay-switcher-eyebrow">{selected ? `Reviewing · ${formatLength(selected.duration)}` : "VOD Review"}</span>
        <span className="replay-switcher-title">{selected?.original_name ?? "Choose a replay"}</span>
      </span>
      {selectedStatus && <span className={`status-badge tone-${selectedStatus.tone}`}>{selectedStatus.label}</span>}
      <ChevronDown size={15} aria-hidden="true" />
    </button>
    {summary && <button type="button" className="replay-switcher-summary" onClick={() => onOpenChange(true)}><span className="dot" aria-hidden="true" />{summary}</button>}

    {open && <div className="replay-switcher-panel" role="dialog" aria-label="Replays">
      <UiInput type="search" aria-label="Filter replays" placeholder="Filter by title" value={filter} onChange={(event) => setFilter(event.target.value)} autoFocus />
      <div className="replay-switcher-section">Ready to review<span>{videos.length}</span></div>
      {loading ? <div className="replay-switcher-empty"><LoaderCircle className="spin" size={15} /> Loading library</div>
        : videos.length === 0 ? <div className="replay-switcher-empty"><strong>No videos yet</strong><span>Add creator sources to import replays automatically, or add a single video.</span></div>
        : visible.length === 0 ? <div className="replay-switcher-empty">No replays match “{filter}”.</div>
        : <ul className="replay-switcher-list">{visible.map((video) => {
          const isNew = unseen.has(video.id);
          const status = videoStatus(video, isNew);
          const current = video.id === selected?.id;
          return <li key={video.id}><button type="button" aria-current={current || undefined} className="replay-option" onClick={() => { onSelect(video.id); onOpenChange(false); }}>
            <span className={`dot ${isNew ? "" : "is-hidden"}`} aria-hidden="true" />
            <span className="replay-option-copy"><span className="replay-option-title">{video.original_name}</span><span className="replay-option-meta">{[formatAdded(video.created_at), formatLength(video.duration), video.mode === "online" ? "Streaming" : null].filter(Boolean).join(" · ")}</span></span>
            <span className={`status-badge tone-${status.tone}`}>{status.label}</span>
          </button></li>;
        })}</ul>}
      {inProgress.length > 0 && <>
        <div className="replay-switcher-section">In progress<span>{inProgress.length}</span></div>
        <ul className="replay-switcher-list">{inProgress.map((item) => <li key={item.id}><button type="button" className="replay-option is-busy" disabled={!item.videoId} onClick={() => { if (item.videoId) { onSelect(item.videoId); onOpenChange(false); } }}>
          <span className="replay-option-copy"><span className="replay-option-title">{item.title}</span>
            <span className="replay-option-progress" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, item.progress ?? 0))}%` }} /></span></span>
          <span className="replay-option-meta">{item.stage}{item.progress !== null ? ` ${Math.round(item.progress)}%` : "…"}</span>
        </button></li>)}</ul>
      </>}
      <div className="replay-switcher-footer">
        <button type="button" onClick={onFindReplays} disabled={findingReplays}>{findingReplays ? <LoaderCircle className="spin" size={14} /> : <ListVideo size={14} />}{findingReplays ? "Finding replays…" : "Find new replays"}</button>
        {extraAction}
      </div>
    </div>}
  </div>;
}
