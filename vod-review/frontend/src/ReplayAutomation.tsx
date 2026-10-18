import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { Modal } from "@/components/shared/modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { NativeSelect } from "@/components/ui/native-select";
import { Checkbox } from "@/components/ui/checkbox";
import { getReplayAutomation, saveReplayAutomation, runReplayAutomation, type ReplayAutomationStatus, type ReplaySchedule, type DownloadQuality } from "./api";

/** Configure creator sources, scheduled imports, and automatic speech transcription. */
export default function ReplayAutomation({ sources, onClose, onImported, onSourcesSaved }: {
  sources: string[]; onClose: () => void; onImported: () => void;
  onSourcesSaved?: (sources: string[]) => void;
}) {
  const [status, setStatus] = useState<ReplayAutomationStatus | null>(null);
  const [draft, setDraft] = useState<ReplaySchedule | null>(null);
  const [sourceText, setSourceText] = useState("");
  const [windowValue, setWindowValue] = useState("24");
  const [windowUnit, setWindowUnit] = useState("hours");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState("");
  const initialized = useRef(false), importedCount = useRef<string | null>(null);
  const importedCallback = useRef(onImported); importedCallback.current = onImported;

  useEffect(() => {
    let cancelled = false;
    /** Poll outcomes without replacing an unsaved form or overwriting creator edits. */
    const refresh = async () => {
      try {
        const result = await getReplayAutomation();
        if (cancelled) return;
        setStatus(result);
        if (!initialized.current) {
          initialized.current = true;
          const configured = result.configured || result.settings.sources.length > 0;
          const initialSources = configured ? result.settings.sources : sources;
          setDraft({ ...result.settings, mode: result.settings.mode ?? "offline", media_type: result.settings.media_type ?? "video", checkpoint_interval_seconds: result.settings.checkpoint_interval_seconds ?? null, transcribe: result.settings.transcribe ?? false, timezone: configured ? result.settings.timezone : Intl.DateTimeFormat().resolvedOptions().timeZone });
          setSourceText(initialSources.join("\n"));
          setWindowValue(String(result.settings.window_hours));
        }
        const count = result.runs.map((run) => `${run.id}:${run.imported}`).join(",");
        if (importedCount.current !== null && importedCount.current !== count) importedCallback.current();
        importedCount.current = count;
      } catch (reason) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load creator schedule");
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, []);

  /** Validate the form and save its settings before an optional explicit scan. */
  const save = async (runNow = false) => {
    if (!draft) return;
    const windowHours = Number(windowValue) * (windowUnit === "days" ? 24 : 1);
    if (!Number.isFinite(windowHours) || windowHours <= 0 || windowHours > 2160) {
      setError("Choose a lookback window greater than zero and no longer than 90 days."); return;
    }
    const creators = [...new Set(sourceText.split(/\r?\n/).map((source) => source.trim().replace(/\/$/, "")).filter(Boolean))];
    if (runNow && !creators.length) { setError("Add at least one creator before running discovery."); return; }
    setBusy(true); setError(null); setSavedMessage("");
    try {
      const result = await saveReplayAutomation({ ...draft, sources: creators, window_hours: windowHours });
      setStatus(result); setDraft(result.settings);
      setSourceText(result.settings.sources.join("\n"));
      onSourcesSaved?.(result.settings.sources);
      if (runNow) {
        await runReplayAutomation();
        setStatus(await getReplayAutomation());
        setSavedMessage(draft.media_type === "audio" ? "Creator scan started. Audio downloads and transcripts will appear in Media." : draft.mode === "online" ? "Creator scan started. Online videos will appear in the library." : draft.transcribe ? "Creator scan started. Videos and transcripts will appear in the library." : "Creator scan started. Imported videos appear in the library.");
      } else setSavedMessage("Schedule saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save creator schedule");
    } finally { setBusy(false); }
  };

  const running = status?.runs.some((run) => run.status === "running");
  const latest = status?.runs[0];
  return <Modal title="Sources and automation" onOpenChange={onClose}>
    <div className="creator-automation">
      <div className="settings-modal-heading"><h2>Sources and automation</h2><Button variant="outline" size="icon-sm" aria-label="Close source settings" onClick={onClose}><X size={17} /></Button></div>
      <p>Save channels for replay discovery, or automatically discover and import their recent videos or audio. Keep VOD Review running and your computer awake for scheduled work.</p>
      {!draft ? <p role="status">Loading schedule…</p> : <form onSubmit={(event) => { event.preventDefault(); void save(); }}>
        <label>Creators<Textarea aria-label="Automatic import creators" rows={5} value={sourceText} onChange={(event) => { setSourceText(event.target.value); setSavedMessage(""); }} placeholder={"https://www.youtube.com/@channel\nhttps://www.twitch.tv/streamer"} /></label>
        <p>One YouTube channel or Twitch streamer URL per line, up to 25. These sources are used for both manual replay discovery and automatic imports.</p>
        <label className="creator-automation-enable"><Checkbox aria-label="Enable daily imports" checked={draft.enabled} onCheckedChange={(checked) => { setDraft({ ...draft, enabled: checked === true }); setSavedMessage(""); }} />Enable daily discovery and downloads</label>
        <div className="creator-automation-fields">
          <label>Daily time<Input aria-label="Daily import time" type="time" required value={draft.daily_time} onChange={(event) => setDraft({ ...draft, daily_time: event.target.value })} /></label>
          <label>Timezone<Input aria-label="Import timezone" required value={draft.timezone} onChange={(event) => setDraft({ ...draft, timezone: event.target.value })} placeholder="America/New_York" /></label>
          <label>Look back<Input aria-label="Import lookback amount" type="number" min="0.01" step="any" required value={windowValue} onChange={(event) => setWindowValue(event.target.value)} /></label>
          <label>Window unit<NativeSelect aria-label="Import lookback unit" value={windowUnit} onChange={(event) => setWindowUnit(event.target.value)}><option value="hours">Hours</option><option value="days">Days</option></NativeSelect></label>
        </div>
        <label>Video quality<NativeSelect aria-label="Automatic import quality" value={draft.quality} onChange={(event) => setDraft({ ...draft, quality: event.target.value as DownloadQuality })}><option value="480p">480p</option><option value="720p">720p</option><option value="1080p">1080p</option><option value="best">Best available</option></NativeSelect></label>
        <div className="creator-automation-fields">
          <label>Import mode<NativeSelect aria-label="Automatic import mode" value={draft.mode} onChange={(event) => { const mode = event.target.value as "online" | "offline"; setDraft({ ...draft, mode, ...(mode === "online" ? { media_type: "video", transcribe: false, checkpoint_interval_seconds: null } : {}) }); setSavedMessage(""); }}><option value="offline">Offline (download)</option><option value="online">Online (stream)</option></NativeSelect></label>
          <label>Media type<NativeSelect aria-label="Automatic import media type" value={draft.media_type} disabled={draft.mode === "online"} onChange={(event) => { const media_type = event.target.value as "video" | "audio"; setDraft({ ...draft, media_type, mode: media_type === "audio" ? "offline" : draft.mode, checkpoint_interval_seconds: media_type === "audio" ? null : draft.checkpoint_interval_seconds }); setSavedMessage(""); }}><option value="video">Video</option><option value="audio">Audio only</option></NativeSelect></label>
          <label>Checkpoint every (seconds)<Input aria-label="Automatic import checkpoint interval" type="number" min="60" max="21600" step="60" disabled={draft.mode === "online" || draft.media_type === "audio"} value={draft.checkpoint_interval_seconds ?? ""} placeholder="Off" onChange={(event) => { const value = event.target.value; setDraft({ ...draft, checkpoint_interval_seconds: value ? Number(value) : null }); setSavedMessage(""); }} /></label>
        </div>
        <p>{draft.mode === "online" ? "Online imports add source-backed video reviews to the library without downloading the video. Choose Offline for sources that cannot be streamed, audio, transcription, or resumable checkpoints." : draft.media_type === "audio" ? "Audio-only imports download the source audio. Enable automatic transcription to recognize speech; completed audio and transcripts are published through Media." : "Offline imports download the full video into the library. Optional checkpoints make long downloads resumable."}</p>
        <label className="creator-automation-enable"><Checkbox aria-label="Automatically transcribe imported videos" disabled={draft.mode === "online"} checked={draft.transcribe} onCheckedChange={(checked) => { setDraft({ ...draft, transcribe: checked === true }); setSavedMessage(""); }} />Automatically transcribe imported media</label>
        <p>{draft.transcribe ? draft.media_type === "audio" ? "Transcribe the downloaded audio automatically; the transcript is shared in Media." : "After each download, recognize speech from the saved video. Transcripts appear when you select the video and are shared in Media." : "Leave transcription off to save media without running speech recognition."}</p>
        <p>Imports use native FPS. Existing full videos and completed transcripts are reused. After downtime, the most recent scheduled window is checked once. Round analysis still requires a saved crop.</p>
        <div className="confirm-modal-actions"><Button variant="outline" type="button" disabled={busy || running} onClick={() => void save(true)}>Run now</Button><Button type="submit" disabled={busy}>{busy ? "Saving…" : "Save schedule"}</Button></div>
      </form>}
      {error && <p role="alert" className="settings-error">{error}</p>}
      {savedMessage && <p role="status">{savedMessage}</p>}
      {status && <section aria-label="Automatic import activity">
        <p>{status.settings.enabled && status.next_run_at ? `Next scan: ${new Date(status.next_run_at).toLocaleString(undefined, { timeZone: status.settings.timezone })} (${status.settings.timezone})` : "Daily imports are off."}</p>
        {latest && <><h3>{latest.status === "running" ? "Checking creators and processing videos…" : `Last run: ${latest.status.replaceAll("_", " ")}`}</h3><p>{latest.imported} imported · {latest.transcribed ?? 0} transcripts ready · {latest.skipped} already available · {latest.matched} found</p>
          {latest.errors.length > 0 && <ul className="creator-automation-errors" aria-label="Creator import errors">{latest.errors.map((item, index) => <li key={index}>{item.source_url && <strong>{item.source_url}: </strong>}{item.message}</li>)}</ul>}</>}
        {status.imports.length > 0 && <ul className="creator-automation-imports">{status.imports.slice(0, 20).map((item) => <li key={item.media_id}><span>{item.title}</span><small>{item.status === "downloading" ? `Downloading ${Math.round(item.progress ?? 0)}%` : item.status === "completed" ? item.media_type === "audio" ? "Audio ready" : item.video_id ? "Video ready" : "Online review ready" : item.status}{item.error ? ` · ${item.error}` : ""}{item.transcription_status ? ` · ${item.transcription_status === "completed" ? "Transcript ready" : item.transcription_status === "running" ? "Transcribing…" : item.transcription_status === "queued" ? "Transcription queued" : "Transcription failed"}` : ""}{item.transcription_error ? ` · ${item.transcription_error}` : ""}</small></li>)}</ul>}
      </section>}
    </div>
  </Modal>;
}
