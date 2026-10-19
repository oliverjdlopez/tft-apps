import { DragEvent, FormEvent, useRef, useState } from "react";
import { LoaderCircle, Upload, X } from "lucide-react";
import { Modal } from "@/components/shared/modal";
import { Button as UiButton } from "@/components/ui/button";
import { Input as UiInput } from "@/components/ui/input";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import type { DownloadQuality } from "./api";

export type AddVideoKind = "stream" | "download" | "audio";

export type AddVideoRequest = {
  url: string;
  kind: AddVideoKind;
  startSeconds: number | null;
  endSeconds: number | null;
  quality: DownloadQuality;
  fps: number | null;
  checkpointSeconds: number | null;
};

const KINDS: { value: AddVideoKind; title: string; description: string }[] = [
  { value: "stream", title: "Stream and review", description: "Fastest. Rounds are found without saving the video. Download later for clips or new transcripts." },
  { value: "download", title: "Download a local copy", description: "Needed for round clips, Drive upload and transcribing. Takes longer." },
  { value: "audio", title: "Transcript only", description: "Downloads audio and transcribes it. No video to review." },
];

/** Parse "h:mm" (or bare minutes, or "h:mm:ss") into seconds; null when blank, NaN when malformed. */
export function parseClock(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return Number.NaN;
  const [first, ...rest] = parts.map(Number);
  if (rest.some((part) => part >= 60)) return Number.NaN;
  if (parts.length === 1) return first * 60;
  return first * 3600 + rest[0] * 60 + (rest[1] ?? 0);
}

export function isOnlineUrl(value: string): boolean {
  try { const url = new URL(value); return /^(?:www\.|m\.)?(?:youtube\.com|youtu\.be)$/.test(url.hostname) || (/^(?:www\.|m\.)?twitch\.tv$/.test(url.hostname) && /^\/(?:videos\/|[^/]+\/video\/)\d+\/?$/.test(url.pathname)); }
  catch { return false; }
}

/** Opt-in manual import: paste a link or upload a file. Automatic discovery remains the primary path. */
export function AddVideoDialog({ initialUrl = "", blockedReason, uploading, onSubmit, onUpload, onClose }: {
  initialUrl?: string;
  blockedReason?: string | null;
  uploading: boolean;
  onSubmit: (request: AddVideoRequest) => Promise<string | null>;
  onUpload: (file: File) => Promise<void>;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"link" | "upload">("link");
  const [url, setUrl] = useState(initialUrl);
  const [kind, setKind] = useState<AddVideoKind>("stream");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [quality, setQuality] = useState<DownloadQuality>("720p");
  const [fps, setFps] = useState("");
  const [checkpoint, setCheckpoint] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const trimmedUrl = url.trim();
  const streamFallback = kind === "stream" && trimmedUrl !== "" && !isOnlineUrl(trimmedUrl);
  const downloads = kind === "download" || streamFallback;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!trimmedUrl) { setFormError("Paste a Twitch or YouTube link first."); return; }
    const startSeconds = kind === "audio" ? null : parseClock(start);
    const endSeconds = kind === "audio" ? null : parseClock(end);
    if (Number.isNaN(startSeconds) || Number.isNaN(endSeconds)) { setFormError("Enter times as h:mm, with minutes from 0–59."); return; }
    if (startSeconds !== null && endSeconds !== null && endSeconds <= startSeconds) { setFormError("The end time must be after the start time."); return; }
    const checkpointMinutes = downloads && checkpoint ? Number(checkpoint) : null;
    setFormError(null);
    setSubmitting(true);
    try {
      const failure = await onSubmit({
        url: trimmedUrl,
        kind: streamFallback ? "download" : kind,
        startSeconds,
        endSeconds,
        quality,
        fps: downloads && fps ? Number(fps) : null,
        checkpointSeconds: checkpointMinutes === null ? null : checkpointMinutes * 60,
      });
      if (failure) setFormError(failure);
    } finally {
      setSubmitting(false);
    }
  };

  const takeFile = (file: File | undefined) => { if (file) void onUpload(file); };
  const handleDrop = (event: DragEvent<HTMLLabelElement>) => { event.preventDefault(); setDragging(false); takeFile(event.dataTransfer.files?.[0]); };

  const busy = submitting || uploading;
  const cta = kind === "audio" ? "Get transcript" : "Add to queue";
  return <Modal title="Add a video" onOpenChange={() => { if (!busy) onClose(); }}>
    <form className="add-video" onSubmit={(event) => void submit(event)}>
      <div className="add-video-heading">
        <div><h2>Add a video</h2><p>For one-off videos. Saved sources are picked up automatically.</p></div>
        <UiButton variant="ghost" size="icon" type="button" aria-label="Close add video" onClick={onClose} disabled={busy}><X size={17} /></UiButton>
      </div>

      <div className="segmented add-video-tabs" role="tablist" aria-label="Video source">
        <button type="button" role="tab" aria-selected={tab === "link"} onClick={() => setTab("link")}>Paste a link</button>
        <button type="button" role="tab" aria-selected={tab === "upload"} onClick={() => setTab("upload")}>Upload a file</button>
      </div>

      {tab === "link" ? <>
        <label className="add-video-field">Twitch or YouTube link
          <UiInput type="url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="https://www.twitch.tv/videos/…" disabled={busy || Boolean(blockedReason)} autoFocus />
        </label>
        <fieldset className="add-video-kinds" disabled={busy || Boolean(blockedReason)}>
          <legend>What to get</legend>
          {KINDS.map((option) => <label key={option.value} className="add-video-kind" data-selected={kind === option.value}>
            <input type="radio" name="add-video-kind" value={option.value} checked={kind === option.value} onChange={() => setKind(option.value)} />
            <span><strong>{option.title}</strong><span>{option.description}</span></span>
          </label>)}
        </fieldset>
        {streamFallback && <p className="add-video-note">Streaming works with YouTube videos and Twitch VODs. This link will be downloaded instead.</p>}
        {kind !== "audio" && <details className="add-video-options">
          <summary>Range and download options</summary>
          <div className="add-video-options-grid">
            <label className="add-video-field">Start (h:mm)<UiInput aria-label="Download start time" value={start} onChange={(event) => setStart(event.target.value)} placeholder="0:00" disabled={busy} /></label>
            <label className="add-video-field">End (h:mm)<UiInput aria-label="Download end time" value={end} onChange={(event) => setEnd(event.target.value)} placeholder="End of video" disabled={busy} /></label>
            {downloads && <>
              <label className="add-video-field">Quality<UiNativeSelect aria-label="Download video quality" value={quality} onChange={(event) => setQuality(event.target.value as DownloadQuality)} disabled={busy}><option value="720p">720p · recommended</option><option value="480p">480p · fastest</option><option value="1080p">1080p</option><option value="best">Best available</option></UiNativeSelect></label>
              <label className="add-video-field">Saved FPS<UiNativeSelect aria-label="Download target FPS" value={fps} onChange={(event) => setFps(event.target.value)} disabled={busy}><option value="">Native</option>{[10, 15, 24, 30, 60].map((value) => <option key={value} value={value}>{value} FPS</option>)}</UiNativeSelect></label>
              <label className="add-video-field">Save checkpoints every<UiNativeSelect aria-label="Download checkpoint interval" value={checkpoint} onChange={(event) => setCheckpoint(event.target.value)} disabled={busy}><option value="">Off</option>{[15, 30, 60].map((value) => <option key={value} value={value}>{value} minutes</option>)}</UiNativeSelect></label>
            </>}
          </div>
          {downloads && fps && <p className="add-video-note">Converting to {fps} FPS adds processing time after the download.</p>}
        </details>}
      </> : <label className={`add-video-drop ${dragging ? "is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={handleDrop}>
        {uploading ? <LoaderCircle className="spin" size={26} /> : <Upload size={26} />}
        <strong>{uploading ? "Uploading…" : "Drop a video file here"}</strong>
        <span>or click to choose one · stays on this machine</span>
        <input ref={fileInput} type="file" aria-label="Video file" accept="video/mp4,video/webm,.mp4,.webm" disabled={uploading} onChange={(event) => { takeFile(event.target.files?.[0]); event.target.value = ""; }} />
      </label>}

      {formError && <p className="add-video-error" role="alert">{formError}</p>}
      {blockedReason && tab === "link" && <p className="add-video-note" role="status">{blockedReason}</p>}

      <div className="add-video-footer">
        <span>It appears under In progress. You can close this and keep reviewing.</span>
        <UiButton variant="outline" type="button" onClick={onClose} disabled={busy}>Cancel</UiButton>
        {tab === "link" && <UiButton type="submit" disabled={busy || Boolean(blockedReason) || !trimmedUrl}>{submitting && <LoaderCircle className="spin" size={15} />}{cta}</UiButton>}
      </div>
    </form>
  </Modal>;
}
