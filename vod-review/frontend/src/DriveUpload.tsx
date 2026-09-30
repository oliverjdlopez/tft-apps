import { Button as UiButton } from "@/components/ui/button";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Input as UiInput } from "@/components/ui/input";
import { useEffect, useId, useState } from "react";
import { LoaderCircle, Upload } from "lucide-react";
import { connectDriveUrl, DriveUploadJob, getDriveConnection, getDriveUpload, uploadRoundsToDrive } from "./api";

/** Upload every parsed round in one VOD and expose recoverable batch progress. */
export default function DriveUpload({ videoId, enabled, offsetSeconds, onOffsetChange, disabledReason = "Process this video to detect round starts before uploading." }: { videoId: string; enabled: boolean; offsetSeconds?: string; onOffsetChange?: (value: string) => void; disabledReason?: string }) {
  const hintId = useId();
  const [keyRoundsOnly, setKeyRoundsOnly] = useState(false);
  const [localOffset, setLocalOffset] = useState("0");
  const [duration, setDuration] = useState("60");
  const offset = offsetSeconds ?? localOffset;
  const options = { key_rounds_only: keyRoundsOnly, offset_seconds: Number(offset), duration_seconds: Number(duration) };
  const validTiming = offset.trim() !== "" && duration.trim() !== "" && Number.isFinite(options.offset_seconds)
    && Math.abs(options.offset_seconds) <= 3600 && Number.isFinite(options.duration_seconds)
    && options.duration_seconds >= 1 && options.duration_seconds <= 180;
  const [connected, setConnected] = useState(false);
  const [job, setJob] = useState<DriveUploadJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    /** Refresh the saved grant when authorization finishes in another tab. */
    async function refreshConnection() {
      try {
        const state = await getDriveConnection();
        if (!disposed) setConnected(state.connected);
      } catch {
        // Upload requests surface configuration/network errors with actionable details.
      }
    }
    void refreshConnection();
    const timer = setInterval(() => void refreshConnection(), 2000);
    window.addEventListener("focus", refreshConnection);
    return () => {
      disposed = true;
      clearInterval(timer);
      window.removeEventListener("focus", refreshConnection);
    };
  }, []);

  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout>;
    /** Recover background progress without updating an unmounted video. */
    async function refresh() {
      try {
        const latest = await getDriveUpload(videoId);
        if (!disposed) {
          setJob(latest);
          setPollError(null);
        }
      } catch (reason) {
        if (!disposed) setPollError(reason instanceof Error ? reason.message : "Could not check upload progress.");
      } finally {
        if (!disposed) timer = setTimeout(() => void refresh(), 2000);
      }
    }
    void refresh();
    return () => { disposed = true; clearTimeout(timer); };
  }, [videoId]);

  /** Submit a batch start or retry and keep authorization errors visible. */
  async function start() {
    setStarting(true);
    setError(null);
    try {
      setJob(await uploadRoundsToDrive(videoId, options));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not upload to Google Drive.");
    } finally {
      setStarting(false);
    }
  }

  const sameOptions = !job?.options || (job.options.key_rounds_only === options.key_rounds_only && job.options.offset_seconds === options.offset_seconds && job.options.duration_seconds === options.duration_seconds);
  const busy = starting || job?.status === "running";
  return <div className="drive-upload">
    <UiButton variant="outline" className="round-export-button" type="button" disabled={!enabled || busy || !validTiming} aria-describedby={!enabled ? hintId : undefined} onClick={() => void start()}
      title={!enabled ? disabledReason : "Upload rounds across this VOD using the selected timing and round filter."}>
      {busy ? <LoaderCircle className="spin" size={12} /> : <Upload size={12} />}
      {busy ? "Uploading…" : job?.status === "failed" && sameOptions ? "Retry GDrive upload" : "Upload to GDrive"}
    </UiButton>
    <label>Rounds <UiNativeSelect aria-label="Rounds to upload" disabled={busy} value={keyRoundsOnly ? "key" : "all"} onChange={(event) => setKeyRoundsOnly(event.target.value === "key")}>
      <option value="all">All rounds</option><option value="key">Key rounds only</option>
    </UiNativeSelect></label>
    <label>Start offset (s) <UiInput aria-label="Upload start offset in seconds" type="number" min="-3600" max="3600" step="any" disabled={busy} value={offset} onChange={(event) => { setLocalOffset(event.target.value); onOffsetChange?.(event.target.value); }} /></label>
    <label>Duration (s) <UiInput aria-label="Upload clip duration in seconds" type="number" min="1" max="180" step="any" disabled={busy} value={duration} onChange={(event) => setDuration(event.target.value)} /></label>
    <span>Key rounds: all of stage 1, each later stage’s first round, plus 3-2 and 4-2. Negative offsets start earlier.</span>
    {!validTiming && <span role="alert">Enter an offset from −3600 to 3600 seconds and a duration from 1 to 180 seconds.</span>}
    {job?.options && <span>Batch: {job.options.key_rounds_only ? "key rounds" : "all rounds"} · offset {job.options.offset_seconds}s · duration {job.options.duration_seconds}s</span>}
    {!enabled && <span id={hintId}>{disabledReason}</span>}
    {connected && <span role="status">Google Drive connected</span>}
    <a href={connectDriveUrl} target="_blank" rel="noreferrer">{connected ? "Reconnect Google Drive" : "Connect Google Drive"}</a>
    {job && <span role="status">{job.status === "completed" ? "Uploaded" : job.status === "failed" ? "Upload stopped:" : "Uploading"} {job.completed}/{job.total} clips</span>}
    {job?.folder_url && <a href={job.folder_url} target="_blank" rel="noreferrer">Open Drive folder</a>}
    {(error || job?.error || pollError) && <span role="alert">{error || job?.error || pollError}</span>}
  </div>;
}
