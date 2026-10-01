import { UploadButton } from "@/components/shared/upload-button";
import { Progress } from "@/components/ui/progress";
import { Modal } from "@/components/shared/modal";
import { Button as UiButton } from "@/components/ui/button";
import { Input as UiInput } from "@/components/ui/input";
import { Alert as UiAlert } from "@/components/ui/alert";
import { Textarea as UiTextarea } from "@/components/ui/textarea";
import { Card as UiCard } from "@/components/ui/card";
import { Badge as UiBadge } from "@/components/ui/badge";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Checkbox as UiCheckbox } from "@/components/ui/checkbox";
import { ChangeEvent, PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Activity, Check, CircleHelp, Cpu, Crosshair, Download, Film, FolderOpen, Link2, ListVideo, LoaderCircle, Pause, Play, RefreshCcw, Save, ScanSearch, Settings, SkipBack, SkipForward, Trash2, TriangleAlert, Upload, X } from "lucide-react";
import { BoundingBox, deleteVideo, dismissPausedDownload, discoverReplays, DownloadMediaType, DownloadQuality, DownloadTask, downloadRoundExport, getDownloadTask, getResumableDownload, getTranscription, getVideo, importVideoUrl, listVideos, pauseDownload, Replay, resumeDownload, RoundExportClip, saveBox, savePausedDownload, SampleResult, startProcessing, startTranscription, TranscriptionTask, uploadVideo, VideoRecord } from "./api";
import DriveUpload from "./DriveUpload";
import ReplayAutomation from "./ReplayAutomation";
import { useOptimizedPlayback } from "./useOptimizedPlayback";

type Point = { x: number; y: number };

export type DetectedGame = {
  number: number;
  results: SampleResult[];
};

type RoundLabel = {
  stage: number;
  round: number;
};

type GameStartCandidate = {
  resultIndex: number;
  startedAt: number;
  lastOpeningRoundIndex: number;
  evidenceCount: number;
  outlierCount: number;
};

const OPENING_ROUNDS = [11, 12, 13, 14, 21, 22] as const;
const MINIMUM_OPENING_EVIDENCE = 3;
const MAXIMUM_OPENING_OUTLIERS = 1;
const MAXIMUM_OPENING_DURATION_SECONDS = 10 * 60;

function parseRoundLabel(label: string): RoundLabel | null {
  const normalized = label.replace(/\D/g, "");
  if (normalized.length !== 2) return null;
  const stage = Number(normalized[0]);
  const round = Number(normalized[1]);
  if (!Number.isInteger(stage) || stage < 1 || stage > 7) return null;
  if (!Number.isInteger(round) || round < 1 || round > 7) return null;
  return { stage, round };
}

function openingRoundIndex(round: RoundLabel): number {
  return OPENING_ROUNDS.indexOf((round.stage * 10 + round.round) as (typeof OPENING_ROUNDS)[number]);
}

function resultTimestamp(result: SampleResult): number {
  return result.scheduled_timestamp_seconds ?? result.timestamp_seconds;
}

function resultKey(result: SampleResult): string {
  return `${result.scheduled_timestamp_seconds}:${result.class_label}`;
}

const MAXIMUM_ROUND_EXPORT_SECONDS = 180;
const REPLAY_SOURCES_STORAGE_KEY = "framewise.replaySources";

function loadReplaySources(): string[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(REPLAY_SOURCES_STORAGE_KEY) ?? "[]");
    return Array.isArray(saved) ? saved.filter((source): source is string => typeof source === "string") : [];
  } catch {
    return [];
  }
}

function parseReplaySources(value: string): string[] {
  return [...new Set(value.split(/\r?\n/).map((source) => source.trim()).filter(Boolean))];
}

function isReplaySourceUrl(value: string): boolean {
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.search || parsed.hash) return false;
    if (host === "youtube.com" || host.endsWith(".youtube.com")) {
      return parts[0]?.startsWith("@") || (["channel", "c", "user"].includes(parts[0]) && parts.length >= 2);
    }
    if (host === "twitch.tv" || host.endsWith(".twitch.tv")) {
      return parts.length === 1 && !["videos", "directory", "downloads", "settings"].includes(parts[0].toLowerCase());
    }
    return false;
  } catch {
    return false;
  }
}

function formatReplayDate(value: string | null): string {
  if (!value) return "Recent upload";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

export function buildRoundExportClips(
  results: SampleResult[],
  selectedKeys: ReadonlySet<string>,
  videoDuration: number,
): RoundExportClip[] {
  return results.flatMap((result, index) => {
    if (!selectedKeys.has(resultKey(result))) return [];
    const start = Math.max(0, result.timestamp_seconds);
    const nextStart = results[index + 1]?.timestamp_seconds ?? videoDuration;
    const end = Math.min(videoDuration, nextStart, start + MAXIMUM_ROUND_EXPORT_SECONDS);
    if (end - start < 0.25) return [];
    return [{ label: result.class_label, start_seconds: start, end_seconds: end }];
  });
}

export function isFeaturedRound(label: string): boolean {
  const round = parseRoundLabel(label);
  if (round === null) return false;
  return round.stage === 1 || round.round === 1 || (round.round === 2 && (round.stage === 3 || round.stage === 4));
}

export function groupRoundTransitions(results: SampleResult[]): DetectedGame[] {
  if (results.length === 0) return [];

  const gameStarts = [0];
  let highestStage = 0;
  let candidate: GameStartCandidate | null = null;

  for (let index = 0; index < results.length; index += 1) {
    const result = results[index];
    const round = parseRoundLabel(result.class_label);
    if (round === null) continue;

    const openingIndex = openingRoundIndex(round);
    const timestamp = resultTimestamp(result);

    if (candidate !== null && timestamp - candidate.startedAt > MAXIMUM_OPENING_DURATION_SECONDS) {
      candidate = null;
    }

    // A newer 1-1 is stronger reset evidence than any unconfirmed candidate.
    if (candidate !== null && openingIndex === 0) {
      candidate = {
        resultIndex: index,
        startedAt: timestamp,
        lastOpeningRoundIndex: openingIndex,
        evidenceCount: 1,
        outlierCount: 0,
      };
      continue;
    }

    if (candidate !== null) {
      if (openingIndex > candidate.lastOpeningRoundIndex) {
        candidate.lastOpeningRoundIndex = openingIndex;
        candidate.evidenceCount += 1;

        if (round.stage >= 2 && candidate.evidenceCount >= MINIMUM_OPENING_EVIDENCE) {
          gameStarts.push(candidate.resultIndex);
          candidate = null;
          highestStage = round.stage;
          continue;
        }
      } else if (openingIndex < 0) {
        candidate.outlierCount += 1;
        if (candidate.outlierCount > MAXIMUM_OPENING_OUTLIERS) candidate = null;
      }
    }

    if (candidate === null && highestStage >= 2 && (openingIndex === 0 || openingIndex === 1)) {
      candidate = {
        resultIndex: index,
        startedAt: timestamp,
        lastOpeningRoundIndex: openingIndex,
        evidenceCount: 1,
        outlierCount: 0,
      };
    }

    highestStage = Math.max(highestStage, round.stage);
  }

  return gameStarts.map((start, index) => ({
    number: index + 1,
    results: results.slice(start, gameStarts[index + 1] ?? results.length),
  }));
}

export function getSeekTimestamp(timestampSeconds: number, offsetSeconds: number, durationSeconds: number): number {
  return Math.max(0, Math.min(durationSeconds, timestampSeconds + offsetSeconds));
}

function formatDuration(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(whole / 60);
  const remaining = whole % 60;
  return `${minutes}:${String(remaining).padStart(2, "0")}`;
}

export function parseTimestamp(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parts = trimmed.split(":");
  if (parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  const numbers = parts.map(Number);
  if (numbers.length > 1 && numbers.slice(1).some((part) => part >= 60)) return null;
  return numbers.reduce((total, part) => total * 60 + part, 0);
}

function parseDownloadTime(hours: string, minutes: string): number | null {
  if (!hours.trim() && !minutes.trim()) return null;
  const parsedHours = hours.trim() ? Number(hours) : 0;
  const parsedMinutes = minutes.trim() ? Number(minutes) : 0;
  if (!Number.isInteger(parsedHours) || parsedHours < 0 || !Number.isInteger(parsedMinutes) || parsedMinutes < 0 || parsedMinutes >= 60) return null;
  return parsedHours * 3600 + parsedMinutes * 60;
}

function App() {
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<VideoRecord | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<VideoRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [videoUrl, setVideoUrl] = useState("");
  const [downloadStartHours, setDownloadStartHours] = useState("");
  const [downloadStartMinutes, setDownloadStartMinutes] = useState("");
  const [downloadEndHours, setDownloadEndHours] = useState("");
  const [downloadEndMinutes, setDownloadEndMinutes] = useState("");
  const [downloadCheckpointMinutes, setDownloadCheckpointMinutes] = useState("");
  const [downloadFps, setDownloadFps] = useState("");
  const [downloadQuality, setDownloadQuality] = useState<DownloadQuality>("720p");
  const [downloadMediaType, setDownloadMediaType] = useState<DownloadMediaType>("video");
  const [transcription, setTranscription] = useState<TranscriptionTask | null>(null);
  const [transcribing, setTranscribing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadTask, setDownloadTask] = useState<DownloadTask | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [automationOpen, setAutomationOpen] = useState(false);
  const [replaySources, setReplaySources] = useState<string[]>(loadReplaySources);
  const [replaySourceDraft, setReplaySourceDraft] = useState("");
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [replays, setReplays] = useState<Replay[] | null>(null);
  const [replayErrors, setReplayErrors] = useState<{ source_url: string; message: string }[]>([]);
  const [discoveringReplays, setDiscoveringReplays] = useState(false);
  const [selectedReplayCreator, setSelectedReplayCreator] = useState("all");
  const analysisSidebarRef = useRef<HTMLDivElement>(null);

  const refreshVideos = useCallback(async () => {
    const records = await listVideos();
    setVideos(records);
    return records;
  }, []);

  useEffect(() => {
    refreshVideos().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load videos")).finally(() => setLoading(false));
  }, [refreshVideos]);

  useEffect(() => {
    // Automatic imports can finish in the backend while this persistent view is idle.
    const refresh = () => { void refreshVideos().catch(() => undefined); };
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [refreshVideos]);

  useEffect(() => {
    if (!selectedId) {
      setSelected(null);
      return;
    }
    let cancelled = false;
    const load = async () => {
      try {
        const record = await getVideo(selectedId);
        if (!cancelled) setSelected(record);
      } catch (reason: unknown) {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Could not load this video");
      }
    };
    load();
    return () => { cancelled = true; };
  }, [selectedId]);

  useEffect(() => {
    setTranscription(null);
  }, [selectedId]);

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    setError(null);
    setUploading(true);
    try {
      const record = await uploadVideo(file);
      setVideos((current) => [record, ...current.filter((video) => video.id !== record.id)]);
      setSelectedId(record.id);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setUploading(false);
      event.target.value = "";
    }
  };

  const selectVideo = (id: string) => {
    setError(null);
    setSelectedId(id);
  };

  const handleDeleteVideo = async () => {
    if (!deleteTarget) return;
    setDeleting(true);
    try {
      await deleteVideo(deleteTarget.id);
      setVideos((current) => current.filter((video) => video.id !== deleteTarget.id));
      if (selectedId === deleteTarget.id) setSelectedId(null);
      setDeleteTarget(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not delete this video");
    } finally {
      setDeleting(false);
    }
  };

  const finishDownload = (record: VideoRecord) => {
    setVideos((current) => [record, ...current.filter((video) => video.id !== record.id)]);
    setSelectedId(record.id);
    setTranscription(null);
    setVideoUrl("");
    setDownloadStartHours("");
    setDownloadStartMinutes("");
    setDownloadEndHours("");
    setDownloadEndMinutes("");
    setDownloadCheckpointMinutes("");
    setDownloadTask(null);
  };

  const pollDownload = async (initial: DownloadTask) => {
    let status = initial;
    setDownloadTask(status);
    while (status.status === "queued" || status.status === "running" || status.status === "pausing") {
      await new Promise((resolve) => window.setTimeout(resolve, 500));
      status = await getDownloadTask(initial.task_id);
      setDownloadTask(status);
      setDownloadProgress(status.progress);
    }
    if (status.status === "paused") {
      if (status.video) setVideos((current) => [status.video!, ...current.filter((video) => video.id !== status.video!.id)]);
      return;
    }
    if (status.media_type === "audio") return;
    if (status.status === "failed" || !status.video) throw new Error(status.error ?? "Could not download this video");
    finishDownload(status.video);
  };

  useEffect(() => {
    getResumableDownload().then((task) => {
      if (!task) return;
      setDownloadTask(task);
      setDownloadProgress(task.progress);
      if (task.status !== "paused") {
        setDownloading(true);
        void pollDownload(task)
          .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not restore this download"))
          .finally(() => setDownloading(false));
      }
    }).catch(() => {});
    // This recovery check intentionally runs once when the app opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleUrlImport = async () => {
    const url = videoUrl.trim();
    if (!url) {
      setError("Paste a Twitch or YouTube URL first.");
      return;
    }
    const startSeconds = parseDownloadTime(downloadStartHours, downloadStartMinutes);
    const endSeconds = parseDownloadTime(downloadEndHours, downloadEndMinutes);
    if (((downloadStartHours.trim() || downloadStartMinutes.trim()) && startSeconds === null) || ((downloadEndHours.trim() || downloadEndMinutes.trim()) && endSeconds === null)) {
      setError("Enter whole hours and minutes from 0–59.");
      return;
    }
    if (startSeconds !== null && endSeconds !== null && endSeconds <= startSeconds) {
      setError("The end timestamp must be after the start timestamp.");
      return;
    }
    const checkpointMinutes = downloadCheckpointMinutes.trim() ? Number(downloadCheckpointMinutes) : null;
    if (checkpointMinutes !== null && (!Number.isInteger(checkpointMinutes) || checkpointMinutes < 1 || checkpointMinutes > 360)) {
      setError("Enter a checkpoint interval from 1 to 360 whole minutes.");
      return;
    }
    setError(null);
    setDownloading(true);
    setDownloadProgress(0);
    try {
      const task = await importVideoUrl(url, startSeconds ?? undefined, endSeconds ?? undefined, checkpointMinutes === null ? undefined : checkpointMinutes * 60, downloadQuality, downloadFps ? Number(downloadFps) : undefined, downloadMediaType, downloadMediaType === "audio");
      await pollDownload(task);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not download this video");
    } finally {
      setDownloading(false);
    }
  };

  const handleTranscribeVideo = async () => {
    if (!selected) return;
    setError(null);
    setTranscribing(true);
    try {
      let task = await startTranscription(selected.id);
      setTranscription(task);
      while (task.status === "queued" || task.status === "running") {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        task = await getTranscription(task.task_id);
        setTranscription(task);
      }
      if (task.status === "failed") setError(task.error ?? "Transcription failed");
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not transcribe this video");
    } finally {
      setTranscribing(false);
    }
  };

  const handlePauseDownload = async () => {
    if (!downloadTask) return;
    try {
      setDownloadTask(await pauseDownload(downloadTask.task_id));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not pause this download");
    }
  };

  const handleResumeDownload = async () => {
    if (!downloadTask) return;
    setError(null);
    setDownloading(true);
    try {
      await pollDownload(await resumeDownload(downloadTask.task_id));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not resume this download");
    } finally {
      setDownloading(false);
    }
  };

  const handleUsePausedDownload = async () => {
    if (!downloadTask) return;
    setError(null);
    try {
      const task = downloadTask.video ? downloadTask : await savePausedDownload(downloadTask.task_id);
      if (!task.video) throw new Error("No completed checkpoint is available yet");
      setVideos((current) => [task.video!, ...current.filter((video) => video.id !== task.video!.id)]);
      setSelectedId(task.video.id);
      setDownloadTask(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not save the paused footage");
    }
  };

  const handleDismissPausedDownload = async () => {
    if (!downloadTask || downloadTask.status !== "paused") return;
    setError(null);
    try {
      await dismissPausedDownload(downloadTask.task_id);
      setDownloadTask(null);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not dismiss the paused download");
    }
  };

  const openSettings = () => {
    setReplaySourceDraft(replaySources.join("\n"));
    setSettingsError(null);
    setSettingsOpen(true);
  };

  const saveReplaySources = () => {
    const sources = parseReplaySources(replaySourceDraft);
    if (sources.length > 25) {
      setSettingsError("Add no more than 25 sources.");
      return;
    }
    if (sources.some((source) => !isReplaySourceUrl(source))) {
      setSettingsError("Use YouTube channel home pages or Twitch streamer home pages, one per line.");
      return;
    }
    try {
      window.localStorage.setItem(REPLAY_SOURCES_STORAGE_KEY, JSON.stringify(sources));
    } catch {
      setSettingsError("These settings could not be saved in this browser.");
      return;
    }
    setReplaySources(sources);
    setReplays(null);
    setSelectedReplayCreator("all");
    setReplayErrors([]);
    setSettingsOpen(false);
  };

  const handleDisplayReplays = async () => {
    if (replaySources.length === 0) {
      openSettings();
      return;
    }
    if (replays !== null) {
      setReplays(null);
      setSelectedReplayCreator("all");
      return;
    }
    setDiscoveringReplays(true);
    setReplayErrors([]);
    try {
      const discovery = await discoverReplays(replaySources);
      setReplays(discovery.replays);
      setSelectedReplayCreator("all");
      setReplayErrors(discovery.errors);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Could not discover new replays");
    } finally {
      setDiscoveringReplays(false);
    }
  };

  const useReplay = (replay: Replay) => {
    setVideoUrl(replay.url);
    setReplays(null);
  };

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark"><ScanSearch size={18} strokeWidth={2.4} /></div>
        <div>
          <p className="eyebrow">VOD REVIEW</p>
          <h1>VOD review and round classification</h1>
        </div>
        <div className="topbar-spacer" />
        <UiButton variant="outline" className="replay-discovery-button" type="button" onClick={() => void handleDisplayReplays()} disabled={discoveringReplays}>
          {discoveringReplays ? <LoaderCircle className="spin" size={16} /> : <ListVideo size={16} />}
          {discoveringReplays ? "Finding replays…" : replays !== null ? "Hide new replays" : "Display new replays"}
        </UiButton>
        <UiButton variant="outline" size="icon-sm" className="settings-button" type="button" aria-label="Replay source settings" onClick={openSettings}>
          <Settings size={18} />
        </UiButton>
        <UiButton variant="outline" className="creator-schedule-button" type="button" aria-label="Automatic creator imports" onClick={() => setAutomationOpen(true)}><RefreshCcw size={16} /><span>Automatic imports</span></UiButton>
        <UploadButton onChange={handleUpload} disabled={uploading}>
          {uploading ? <LoaderCircle className="spin" size={17} /> : <Upload size={17} />}
          {uploading ? "Uploading…" : "Upload video"}
        </UploadButton>
      </header>

      {error && <UiAlert variant="destructive" className="toast error-toast"><X size={16} /> {error}<UiButton variant="outline" onClick={() => setError(null)} aria-label="Dismiss error">Dismiss</UiButton></UiAlert>}
      {automationOpen && <ReplayAutomation sources={replaySources} onClose={() => setAutomationOpen(false)} onImported={() => { void refreshVideos().catch(() => undefined); }} />}
      {settingsOpen && <Modal title="Source settings" onOpenChange={() => setSettingsOpen(false)}><div className="settings-modal-heading"><div><p className="eyebrow">REPLAY DISCOVERY</p><h2 id="replay-settings-title">Source settings</h2></div><UiButton variant="outline" type="button" aria-label="Close replay source settings" onClick={() => setSettingsOpen(false)}><X size={17} /></UiButton></div><p>Add one YouTube channel home page or Twitch streamer home page per line. These stay in this browser.</p><label htmlFor="replay-source-list">Replay sources</label><UiTextarea id="replay-source-list" rows={7} value={replaySourceDraft} onChange={(event) => { setReplaySourceDraft(event.target.value); setSettingsError(null); }} placeholder={"https://www.youtube.com/@channel\nhttps://www.twitch.tv/streamer"} autoFocus />{settingsError && <div className="settings-error" role="alert"><TriangleAlert size={14} />{settingsError}</div>}<div className="confirm-modal-actions"><UiButton variant="outline" className="secondary-button" type="button" onClick={() => setSettingsOpen(false)}>Cancel</UiButton><UiButton variant="default" className="primary-button" type="button" onClick={saveReplaySources}>Save sources</UiButton></div></Modal>}
      {deleteTarget && <Modal title="Delete saved VOD?" destructive onOpenChange={() => { if (!deleting) setDeleteTarget(null); }}><div className="confirm-modal-icon"><Trash2 size={19} /></div><h2 id="delete-video-title">Delete saved VOD?</h2><p>“{deleteTarget.original_name}” and its analysis data will be permanently removed from this machine.</p><div className="confirm-modal-actions"><UiButton variant="outline" className="secondary-button" type="button" onClick={() => setDeleteTarget(null)} disabled={deleting}>Cancel</UiButton><UiButton variant="destructive" className="danger-button" type="button" onClick={() => void handleDeleteVideo()} disabled={deleting}>{deleting ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}{deleting ? "Deleting…" : "Delete VOD"}</UiButton></div></Modal>}

      {replays !== null && <section className="replay-panel" aria-labelledby="new-replays-title"><div className="replay-panel-heading"><div><p className="eyebrow">DISCOVERED FROM {replaySources.length} {replaySources.length === 1 ? "SOURCE" : "SOURCES"}</p><h2 id="new-replays-title">New replays</h2></div><UiButton variant="outline" type="button" aria-label="Close new replays" onClick={() => { setReplays(null); setSelectedReplayCreator("all"); }}><X size={17} /></UiButton></div>{replays.length === 0 ? <div className="replay-empty"><ListVideo size={21} /><span>No recent videos or VODs were found.</span></div> : <><label className="replay-creator-filter">Creator<UiNativeSelect aria-label="Filter replays by creator" value={selectedReplayCreator} onChange={(event) => setSelectedReplayCreator(event.target.value)}><option value="all">All creators</option>{[...new Set(replays.map((replay) => replay.creator))].sort((a, b) => a.localeCompare(b)).map((creator) => <option key={creator} value={creator}>{creator}</option>)}</UiNativeSelect></label><div className="replay-list">{replays.filter((replay) => selectedReplayCreator === "all" || replay.creator === selectedReplayCreator).map((replay) => <article className="replay-card" key={replay.id}>{replay.thumbnail_url ? <img src={replay.thumbnail_url} alt="" /> : <div className={`replay-thumbnail ${replay.platform}`}><Play size={20} /></div>}<div className="replay-card-copy"><span className={`platform-pill ${replay.platform}`}>{replay.platform === "youtube" ? "YouTube" : "Twitch"}</span><h3>{replay.title}</h3><p>{replay.creator} · {formatReplayDate(replay.published_at)}{replay.duration_seconds ? ` · ${formatDuration(replay.duration_seconds)}` : ""}</p></div><UiButton variant="outline" className="secondary-button" type="button" onClick={() => useReplay(replay)}>Use replay</UiButton></article>)}</div></>}{replayErrors.length > 0 && <div className="replay-source-errors" role="status"><TriangleAlert size={14} /><span>{replayErrors.length} {replayErrors.length === 1 ? "source could" : "sources could"} not be checked. Open settings to review the URLs.</span></div>}</section>}

      <main className="workspace">
        <UiCard as="aside" className="library-panel panel block gap-0 p-4 sm:p-6 shadow-xs">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">LIBRARY</p>
              <h2>Video</h2>
            </div>
            <UiBadge variant="secondary" className="count-pill">{videos.length}</UiBadge>
          </div>
          {loading ? <div className="empty-state compact"><LoaderCircle className="spin" size={18} /> Loading library</div> : videos.length === 0 ? (
            <div className="empty-state"><FolderOpen size={24} /><strong>No videos yet</strong><span>Upload a file or paste a video link to begin.</span></div>
          ) : (
            <div className="video-picker">
              <div className="video-picker-heading"><span>Recent videos</span>{selected && <UiButton variant="destructive" className="delete-video-button" type="button" aria-label={`Delete ${selected.original_name}`} onClick={() => setDeleteTarget(selected)}><Trash2 size={13} /> Delete</UiButton>}</div>
              <UiNativeSelect aria-label="Recent videos" value={selectedId ?? ""} onChange={(event) => selectVideo(event.target.value)}>
                <option value="" disabled>Choose a video…</option>
                {videos.map((video) => <option key={video.id} value={video.id}>{video.original_name} · {formatDuration(video.duration)}</option>)}
              </UiNativeSelect>
            </div>
          )}
          <form className="url-import" onSubmit={(event) => { event.preventDefault(); void handleUrlImport(); }}>
            <label htmlFor="video-url"><Link2 size={13} /> Twitch or YouTube URL</label>
            <label className="url-import-quality">Download type<UiNativeSelect aria-label="Download type" value={downloadMediaType} onChange={(event) => setDownloadMediaType(event.target.value as DownloadMediaType)} disabled={downloading || downloadTask?.status === "paused"}><option value="video">Video for analysis</option><option value="audio">Audio only, then transcribe</option></UiNativeSelect></label>
            <div className="url-import-row">
              <UiInput id="video-url" type="url" value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="Paste a video link…" disabled={downloading || downloadTask?.status === "paused"} />
              <UiButton variant="outline" type="submit" disabled={downloading || downloadTask?.status === "paused" || !videoUrl.trim()} aria-label={downloadMediaType === "audio" ? "Download and transcribe audio from link" : "Download video from link"}>
                {downloading ? <LoaderCircle className="spin" size={15} /> : <Download size={15} />}
              </UiButton>
            </div>
            {downloadMediaType === "video" && <div className="url-import-range">
              <input className="legacy-time-input" aria-label="Download start timestamp" tabIndex={-1} value="" onChange={(event) => { const value = parseTimestamp(event.target.value); setDownloadStartHours(value === null ? "" : String(Math.floor(value / 3600))); setDownloadStartMinutes(value === null ? "" : String(Math.floor(value / 60) % 60)); }} />
              <input className="legacy-time-input" aria-label="Download end timestamp" tabIndex={-1} value="" onChange={(event) => { const value = parseTimestamp(event.target.value); setDownloadEndHours(value === null ? "" : String(Math.floor(value / 3600))); setDownloadEndMinutes(value === null ? "" : String(Math.floor(value / 60) % 60)); }} />
              <fieldset><legend>Start time</legend><div className="time-inputs"><label>Hours<UiInput aria-label="Download start hours" type="number" min="0" step="1" inputMode="numeric" value={downloadStartHours} onChange={(event) => setDownloadStartHours(event.target.value)} placeholder="0" disabled={downloading} /></label><label>Minutes<UiInput aria-label="Download start minutes" type="number" min="0" max="59" step="1" inputMode="numeric" value={downloadStartMinutes} onChange={(event) => setDownloadStartMinutes(event.target.value)} placeholder="0" disabled={downloading} /></label></div></fieldset>
              <span aria-hidden="true">–</span>
              <fieldset><legend>End time</legend><div className="time-inputs"><label>Hours<UiInput aria-label="Download end hours" type="number" min="0" step="1" inputMode="numeric" value={downloadEndHours} onChange={(event) => setDownloadEndHours(event.target.value)} placeholder="0" disabled={downloading} /></label><label>Minutes<UiInput aria-label="Download end minutes" type="number" min="0" max="59" step="1" inputMode="numeric" value={downloadEndMinutes} onChange={(event) => setDownloadEndMinutes(event.target.value)} placeholder="0" disabled={downloading} /></label></div></fieldset>
            </div>}
            {downloadMediaType === "video" && <><label className="url-import-quality">Video quality<UiNativeSelect aria-label="Download video quality" value={downloadQuality} onChange={(event) => setDownloadQuality(event.target.value as DownloadQuality)} disabled={downloading || downloadTask?.status === "paused"}><option value="480p">480p · fastest</option><option value="720p">720p · recommended</option><option value="1080p">1080p</option><option value="best">Best available</option></UiNativeSelect></label>
            <label className="url-import-quality">Saved video FPS<UiNativeSelect aria-label="Download target FPS" value={downloadFps} onChange={(event) => setDownloadFps(event.target.value)} disabled={downloading || downloadTask?.status === "paused"}><option value="">Native</option>{[10, 15, 24, 30, 60].map((fps) => <option key={fps} value={fps}>{fps} FPS</option>)}</UiNativeSelect></label>
            {downloadFps && <span>Converts the saved video to {downloadFps} FPS after downloading. This adds processing time.</span>}
            <label className="url-import-checkpoint">Checkpoint every <span><UiInput aria-label="Download checkpoint interval in minutes" type="number" min="1" max="360" step="1" inputMode="numeric" value={downloadCheckpointMinutes} onChange={(event) => setDownloadCheckpointMinutes(event.target.value)} placeholder="Off" disabled={downloading || downloadTask?.status === "paused"} /> minutes</span></label></>}
            {downloadTask && downloadTask.status !== "completed" && downloadTask.status !== "failed" && downloadTask.status !== "dismissed" && <div className="download-progress" role="status" aria-label={`Download progress: ${Math.round(downloadProgress)} percent`}><div className="download-progress-copy"><span>{downloadTask.status === "paused" ? "Download paused" : downloadTask.status === "pausing" ? "Pausing after this checkpoint…" : downloadTask.transcription?.status === "running" ? "Transcribing audio…" : "Downloading your VOD…"}</span><strong>{Math.round(downloadProgress)}%</strong></div><Progress aria-label="Download progress" value={downloadProgress} />{downloadTask.status === "paused" ? <div className="download-controls"><UiButton variant="outline" className="download-control" type="button" onClick={() => void handleUsePausedDownload()}><Film size={11} /> Use saved footage</UiButton><UiButton variant="outline" className="download-control" type="button" onClick={() => void handleResumeDownload()}><Play size={11} /> Resume</UiButton><UiButton variant="outline" className="download-control" type="button" onClick={() => void handleDismissPausedDownload()}><X size={11} /> Dismiss</UiButton></div> : downloadCheckpointMinutes && <UiButton variant="outline" className="download-control" type="button" disabled={downloadTask.status === "pausing"} onClick={() => void handlePauseDownload()}><Pause size={11} /> {downloadTask.status === "pausing" ? "Pause requested" : "Pause"}</UiButton>}</div>}<span>{downloading ? "Completed checkpoints are kept if the download is interrupted." : downloadTask?.status === "paused" ? "Use the saved footage now or resume from the last checkpoint." : "Optional range and checkpoints · leave checkpoint blank for a standard download."}</span>
          </form>
          {selected && <div className="download-progress"><div className="download-progress-copy"><span>Optional raw speech transcription</span></div><UiButton variant="outline" className="download-control" type="button" disabled={transcribing} onClick={() => void handleTranscribeVideo()}>{transcribing ? <><LoaderCircle className="spin" size={12} /> Transcribing…</> : "Transcribe selected video"}</UiButton>{transcription?.status === "completed" && <><span>{transcription.language ? `Detected language: ${transcription.language}` : "Transcript"}</span><UiTextarea aria-label="Raw transcript" value={transcription.transcript ?? ""} readOnly rows={6} /></>}</div>}
          {downloadTask?.media_type === "audio" && <div className="download-progress"><div className="download-progress-copy"><span>{downloadTask.status === "failed" ? (downloadTask.transcription?.error ?? downloadTask.error ?? "Audio transcription failed") : downloadTask.transcription?.status === "completed" ? `Transcription complete${downloadTask.transcription.language ? ` · ${downloadTask.transcription.language}` : ""}` : "Downloading and transcribing audio…"}</span></div>{downloadTask.transcription?.transcript && <UiTextarea aria-label="Raw audio transcript" value={downloadTask.transcription.transcript} readOnly rows={8} />}</div>}
          <div ref={analysisSidebarRef} className="analysis-sidebar-results" />
          <div className="library-footnote"><CircleHelp size={14} /> Your uploads stay on this machine.</div>
        </UiCard>

        <UiCard as="section" id="workspace-panel" aria-label="Round analysis" tabIndex={0} className="analysis-panel panel block gap-0 p-4 sm:p-6 shadow-xs">
          {selected ? <Analyzer video={selected} sidebarTarget={analysisSidebarRef.current} onUpdate={(record) => { setSelected(record); setVideos((current) => current.map((item) => item.id === record.id ? record : item)); }} onError={setError} /> : (
            <div className="welcome-state">
              <div className="welcome-icon"><Film size={28} /></div>
              <p className="eyebrow">READY WHEN YOU ARE</p>
              <h2>Find the moment that matters.</h2>
              <p>Upload a VOD, choose a frame, and draw a fixed region to analyze at your chosen snapshot interval.</p>
              <UploadButton onChange={handleUpload} disabled={uploading}><Upload size={17} />Choose a video</UploadButton>
            </div>
          )}
        </UiCard>
      </main>
    </div>
  );
}

function Analyzer({ video, sidebarTarget, onUpdate, onError }: { video: VideoRecord; sidebarTarget: HTMLDivElement | null; onUpdate: (video: VideoRecord) => void; onError: (message: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const initialSeekPending = useRef(true);
  const playback = useOptimizedPlayback(video.id, videoRef);
  const overlayRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [draftBox, setDraftBox] = useState<BoundingBox | null>(video.box);
  const [boxEditing, setBoxEditing] = useState(false);
  const [drawing, setDrawing] = useState<Point | null>(null);
  const [currentTime, setCurrentTime] = useState(video.box?.frame_time ?? 0);
  const wasPlayingWhenHidden = useRef(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [analysisInterval, setAnalysisInterval] = useState(String(video.latest_job?.sample_interval_seconds ?? 1));
  const [batchSize, setBatchSize] = useState(video.latest_job?.batch_size ?? 64);
  const [offsetSeconds, setOffsetSeconds] = useState("0");
  const [selectedGameIndex, setSelectedGameIndex] = useState(0);
  const [showAllRounds, setShowAllRounds] = useState(false);
  const [selectedRoundKeys, setSelectedRoundKeys] = useState<Set<string>>(new Set());
  const [exportingRounds, setExportingRounds] = useState(false);

  const activeJob = video.active_job;
  const currentJob = video.current_job;
  const latestJob = video.latest_job ?? currentJob;
  const isProcessing = activeJob?.status === "queued" || activeJob?.status === "running";
  const results = currentJob?.results ?? [];
  const games = useMemo(() => groupRoundTransitions(results), [results]);
  const selectedGameResults = games[selectedGameIndex]?.results ?? [];
  const selectedGameEnd = games[selectedGameIndex + 1]?.results[0]?.timestamp_seconds ?? video.duration;
  const featuredResults = selectedGameResults.filter((result) => isFeaturedRound(result.class_label));
  const hiddenRoundCount = selectedGameResults.length - featuredResults.length;
  const visibleResults = showAllRounds ? selectedGameResults : featuredResults;
  const selectedRoundCount = selectedGameResults.filter((result) => selectedRoundKeys.has(resultKey(result))).length;

  useEffect(() => {
    initialSeekPending.current = true;
  }, [video.id]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      const element = videoRef.current;
      if (!element) return;
      if (document.hidden) {
        wasPlayingWhenHidden.current = !element.paused && !element.ended;
        return;
      }
      if (!wasPlayingWhenHidden.current) return;
      wasPlayingWhenHidden.current = false;

      // Background tab throttling can leave the audio clock advancing while
      // the decoded video frame is stuck. A seek flushes the decoder pipeline.
      const time = Number.isFinite(element.currentTime) ? element.currentTime : 0;
      const duration = Number.isFinite(element.duration) ? element.duration : video.duration;
      element.pause();
      element.currentTime = Math.min(duration, time + 0.05);
      void element.play().catch(() => undefined);
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, []);

  useEffect(() => {
    setDraftBox(video.box);
    setBoxEditing(false);
    setDrawing(null);
  }, [video.id, video.box]);

  useEffect(() => {
    setAnalysisInterval(String(video.latest_job?.sample_interval_seconds ?? 1));
    setBatchSize(video.latest_job?.batch_size ?? 64);
    setOffsetSeconds("0");
    setSelectedGameIndex(0);
    setShowAllRounds(false);
  }, [video.id]);

  useEffect(() => {
    setShowAllRounds(false);
  }, [selectedGameIndex]);

  useEffect(() => {
    setSelectedRoundKeys(new Set(
      selectedGameResults
        .filter((result) => isFeaturedRound(result.class_label))
        .map(resultKey),
    ));
  }, [video.id, currentJob?.id, selectedGameIndex, selectedGameResults.length]);

  useEffect(() => {
    if (selectedGameIndex >= games.length) setSelectedGameIndex(Math.max(0, games.length - 1));
  }, [games.length, selectedGameIndex]);

  useEffect(() => {
    if (!isProcessing) return;
    let cancelled = false;
    let timer: number | undefined;
    const poll = async () => {
      try {
        const fresh = await getVideo(video.id);
        if (!cancelled) onUpdate(fresh);
      } catch (reason: unknown) {
        if (!cancelled) onError(reason instanceof Error ? reason.message : "Could not refresh processing status");
      } finally {
        // Reschedule even when status stays running and callbacks are stable.
        if (!cancelled) timer = window.setTimeout(poll, 750);
      }
    };
    timer = window.setTimeout(poll, 750);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [isProcessing, video.id, onUpdate, onError]);

  useEffect(() => {
    let disposed = false;
    /** Recover results completed in another tab while Google login was open. */
    async function refreshOnReturn() {
      try {
        const fresh = await getVideo(video.id);
        if (!disposed) onUpdate(fresh);
      } catch (reason) {
        if (!disposed) onError(reason instanceof Error ? reason.message : "Could not refresh video status");
      }
    }
    window.addEventListener("focus", refreshOnReturn);
    return () => { disposed = true; window.removeEventListener("focus", refreshOnReturn); };
  }, [video.id, onUpdate, onError]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const overlay = overlayRef.current;
    if (!canvas || !overlay) return;
    const rect = overlay.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(rect.width * ratio));
    canvas.height = Math.max(1, Math.floor(rect.height * ratio));
    canvas.style.width = `${rect.width}px`;
    canvas.style.height = `${rect.height}px`;
    const context = canvas.getContext("2d");
    if (!context) return;
    context.scale(ratio, ratio);
    context.clearRect(0, 0, rect.width, rect.height);
    if (!draftBox) return;
    const x = draftBox.x * rect.width;
    const y = draftBox.y * rect.height;
    const width = draftBox.width * rect.width;
    const height = draftBox.height * rect.height;
    context.fillStyle = "rgba(84, 214, 178, 0.12)";
    context.fillRect(x, y, width, height);
    context.strokeStyle = "#59e0b8";
    context.lineWidth = 2;
    context.setLineDash([7, 5]);
    context.strokeRect(x, y, width, height);
    context.setLineDash([]);
    context.fillStyle = "#59e0b8";
    context.font = "600 11px ui-monospace, SFMono-Regular, Menlo, monospace";
    context.fillText("ANALYSIS REGION", x + 8, Math.max(y - 8, 15));
  }, [draftBox]);

  useEffect(() => {
    redraw();
    const observer = new ResizeObserver(redraw);
    if (overlayRef.current) observer.observe(overlayRef.current);
    return () => observer.disconnect();
  }, [redraw]);

  const getPoint = (event: PointerEvent<HTMLCanvasElement>): Point => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), y: Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height)) };
  };

  const handlePointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!boxEditing) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    setDrawing(getPoint(event));
    setDraftBox(null);
  };
  const handlePointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    if (!drawing) return;
    const current = getPoint(event);
    const x = Math.min(drawing.x, current.x);
    const y = Math.min(drawing.y, current.y);
    setDraftBox({ x, y, width: Math.abs(current.x - drawing.x), height: Math.abs(current.y - drawing.y), frame_time: currentTime });
  };
  const handlePointerUp = () => setDrawing(null);

  const saveCurrentBox = async () => {
    if (!draftBox || draftBox.width < 0.01 || draftBox.height < 0.01) {
      onError("Draw a larger analysis region first.");
      return;
    }
    setSaving(true);
    try {
      const fresh = await saveBox(video.id, { ...draftBox, frame_time: currentTime });
      setDraftBox(fresh.box);
      setBoxEditing(false);
      onUpdate(fresh);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not save the box");
    } finally {
      setSaving(false);
    }
  };

  const process = async (reuseCachedCrops = false) => {
    const interval = Number(analysisInterval);
    if (!analysisInterval.trim() || !Number.isFinite(interval) || interval < 0 || interval > 3600) {
      onError("Enter an analysis interval from 0 to 3600 seconds; 0 analyzes every frame.");
      return;
    }
    setStarting(true);
    try {
      await startProcessing(video.id, batchSize, interval, reuseCachedCrops);
      const fresh = await getVideo(video.id);
      onUpdate(fresh);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not start processing");
    } finally {
      setStarting(false);
    }
  };

  const jumpTo = (result: SampleResult) => {
    if (!videoRef.current) return;
    const parsedOffset = Number(offsetSeconds);
    const seekTime = getSeekTimestamp(
      result.timestamp_seconds,
      Number.isFinite(parsedOffset) ? parsedOffset : 0,
      video.duration,
    );
    videoRef.current.currentTime = seekTime;
    setCurrentTime(seekTime);
    void videoRef.current.play().catch(() => undefined);
  };

  const skipPlayback = (seconds: number) => {
    const element = videoRef.current;
    if (!element) return;
    const duration = Number.isFinite(element.duration) ? element.duration : video.duration;
    const time = Math.max(0, Math.min(duration, element.currentTime + seconds));
    element.currentTime = time;
    setCurrentTime(time);
  };

  const toggleRoundSelection = (result: SampleResult) => {
    const key = resultKey(result);
    setSelectedRoundKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const exportSelectedRounds = async () => {
    const clips = buildRoundExportClips(selectedGameResults, selectedRoundKeys, selectedGameEnd);
    if (clips.length === 0) {
      onError("Select at least one round with a usable duration first.");
      return;
    }
    setExportingRounds(true);
    try {
      const blob = await downloadRoundExport(video.id, selectedGameIndex + 1, clips);
      const objectUrl = URL.createObjectURL(blob);
      const sourceName = video.original_name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9._-]+/g, "-") || "video";
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = `${sourceName}-game-${selectedGameIndex + 1}-rounds.mp4`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1_000);
    } catch (reason: unknown) {
      onError(reason instanceof Error ? reason.message : "Could not export the selected rounds");
    } finally {
      setExportingRounds(false);
    }
  };

  const hasBox = Boolean(video.box);
  const progress = activeJob && activeJob.total_samples > 0
    ? Math.min(100, Math.round((activeJob.phase === "preparing" ? activeJob.collected_samples / activeJob.total_samples : (activeJob.collected_samples + activeJob.progress) / (activeJob.total_samples * 2)) * 100))
    : 0;
  const deviceLabel = activeJob?.device ?? latestJob?.device;
  const timingError = currentJob?.max_timing_error_ms ?? null;
  const hasTimingWarning = timingError !== null && timingError > 100;
  const roundTransitions = <div className="results-section"><DriveUpload key={video.id} videoId={video.id} offsetSeconds={offsetSeconds} onOffsetChange={setOffsetSeconds} enabled={currentJob?.status === "completed" && results.length > 0} disabledReason={isProcessing ? "Round classification is still running. Upload becomes available when round starts are ready." : currentJob?.status === "completed" ? "No round starts were detected. Check the round crop and process the video again." : "Process this video to detect round starts before uploading."} /><div className="results-heading"><div><p className="eyebrow">ROUND TRANSITIONS</p><h3>Confirmed round changes</h3></div><div className="result-statuses">{selectedGameResults.length > 0 && <UiButton variant="outline" className="round-export-button" type="button" disabled={selectedRoundCount === 0 || exportingRounds} onClick={() => void exportSelectedRounds()}>{exportingRounds ? <LoaderCircle className="spin" size={12} /> : <Download size={12} />}{exportingRounds ? "Building video…" : `Download selected (${selectedRoundCount})`}</UiButton>}{hiddenRoundCount > 0 && <UiButton variant="outline" className="round-visibility-button" type="button" aria-expanded={showAllRounds} onClick={() => setShowAllRounds((visible) => !visible)}>{showAllRounds ? "Show key rounds" : `Show ${hiddenRoundCount} more`}</UiButton>}{games.length > 1 && <label className="game-select"><span>Game</span><UiNativeSelect aria-label="Select game" value={selectedGameIndex} onChange={(event) => setSelectedGameIndex(Number(event.target.value))}>{games.map((game, index) => <option key={game.number} value={index}>Game {game.number} · {game.results.length} rounds</option>)}</UiNativeSelect></label>}{currentJob?.status === "completed" && timingError !== null && <span className={`timing-pill ${hasTimingWarning ? "warning" : ""}`}>{hasTimingWarning ? <TriangleAlert size={12} /> : <Check size={12} />} PTS ±{Math.round(timingError)} ms</span>}{latestJob?.status === "completed" && <UiBadge variant="secondary" className="complete-pill"><Check size={13} /> Complete</UiBadge>}</div></div>{results.length === 0 ? <div className="results-empty"><Activity size={20} /><span>{hasBox ? "Process the video to find confirmed round changes." : "Draw and save a box to enable processing."}</span></div> : <div className="results-list">{visibleResults.map((result) => <ResultRow key={result.scheduled_timestamp_seconds} result={result} selected={selectedRoundKeys.has(resultKey(result))} onSelectionChange={() => toggleRoundSelection(result)} onClick={() => jumpTo(result)} />)}</div>}</div>;

  const sidebar = roundTransitions;
  return <><div className="analyzer">
    <div className="analyzer-heading"><div><p className="eyebrow">ROUND ANALYSIS</p><h2>{video.original_name}</h2></div><div className="video-meta"><span>{video.width} × {video.height}</span><span>{formatDuration(video.duration)}</span></div></div>
    <div className="video-stage-wrap">
      <div className="video-stage" ref={overlayRef} style={{ aspectRatio: `${video.width} / ${video.height}` }}>
        <video ref={videoRef} controls playsInline preload="metadata" onPause={(event) => { setCurrentTime(event.currentTarget.currentTime); }} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} onLoadedMetadata={(event) => { if (!initialSeekPending.current) return; initialSeekPending.current = false; const initialTime = video.box?.frame_time ?? 0; event.currentTarget.currentTime = initialTime; setCurrentTime(initialTime); }} />
        {playback.status === "preparing" && <div className="playback-status"><LoaderCircle className="spin" size={18} /><strong>Preparing fast playback…</strong><span>This one-time step makes startup and scrubbing responsive.</span></div>}
        {playback.status === "failed" && playback.error && <div className="playback-warning"><span>{playback.error ?? "Optimized playback is unavailable."}</span><UiButton variant="outline" type="button" onClick={() => void playback.retry()}>Retry</UiButton></div>}
        <canvas ref={canvasRef} className={`box-canvas ${boxEditing ? "is-editing" : ""}`} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp} aria-label="Draw a bounding box on the video" />
        {boxEditing && !draftBox && <div className="canvas-hint"><span>+</span><strong>Draw an analysis region</strong><small>Click and drag on the video</small></div>}
      </div>
    </div>
    <div className="video-skip-controls" aria-label="Video seek controls">
      <UiButton variant="outline" type="button" aria-label="Rewind 5 seconds" onClick={() => skipPlayback(-5)}><SkipBack size={16} /> 5 seconds</UiButton>
      <UiButton variant="outline" type="button" aria-label="Skip forward 5 seconds" onClick={() => skipPlayback(5)}>5 seconds <SkipForward size={16} /></UiButton>
    </div>
    <div className="workspace-actions"><div className="frame-readout"><span className="status-dot" /> Current frame <strong>{formatDuration(currentTime)}</strong></div><div className="action-buttons"><UiButton variant={boxEditing ? "secondary" : "outline"} aria-pressed={boxEditing} className={`secondary-button ${boxEditing ? "active-tool" : ""}`} onClick={() => { setDrawing(null); setBoxEditing((current) => !current); }}><Crosshair size={16} />{boxEditing ? "Exit drawing" : hasBox ? "Edit box" : "Draw box"}</UiButton><UiButton variant="outline" className="secondary-button" disabled={!draftBox || saving} onClick={saveCurrentBox}>{saving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}{saving ? "Saving…" : hasBox ? "Update box" : "Save box"}</UiButton><label className="batch-size-control" title="Elapsed time between analyzed frames. 0 checks every frame."><span>Interval (s)</span><UiInput aria-label="Analysis interval in seconds" type="number" min="0" max="3600" step="any" value={analysisInterval} disabled={isProcessing || starting} onChange={(event) => setAnalysisInterval(event.target.value)} /></label><label className="batch-size-control"><span>Batch</span><UiInput type="number" min="1" max="256" value={batchSize} disabled={isProcessing || starting} onChange={(event) => setBatchSize(Math.max(1, Math.min(256, Number(event.target.value) || 1)))} /></label><label className="offset-control"><span>Offset (s)</span><UiInput aria-label="Seek offset in seconds" type="number" step="1" value={offsetSeconds} onChange={(event) => setOffsetSeconds(event.target.value)} /></label>{latestJob?.status === "completed" && <UiButton variant="outline" className="secondary-button" disabled={isProcessing || starting} onClick={() => process(true)}><RefreshCcw size={16} /> Rerun OCR</UiButton>}<UiButton variant="default" className="primary-button" disabled={!hasBox || isProcessing || starting} onClick={() => process(false)}>{isProcessing ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}{isProcessing ? `${activeJob?.phase === "preparing" ? "Preparing" : "Analyzing"} ${progress}%` : latestJob?.status === "completed" ? "Analyze again" : latestJob?.status === "failed" ? "Retry analysis" : "Process video"}</UiButton></div></div>
    <p className="analysis-note">Sampled frames are cached for reuse across round-analysis runs. Preparation and analysis show separate progress.</p>
    <p className="analysis-note">{Number(analysisInterval) > 0 ? `About ${Math.ceil(video.duration / Number(analysisInterval)).toLocaleString()} samples for this video, one every ${analysisInterval} seconds.` : "Every-frame mode: all source frames will be prepared and analyzed."}</p>
    <p className="analysis-note">Analysis interval: 0 checks every frame; 0.1 samples about 10 frames per second. Timestamp clicks use the actual selected frame.</p>
    {isProcessing && <div className="progress-card"><div className="progress-copy"><div><span className="eyebrow">{activeJob?.sample_interval_seconds === 0 ? "EVERY FRAME" : `EVERY ${activeJob?.sample_interval_seconds} SECONDS`} · BATCH SIZE {activeJob?.batch_size}</span><strong>{activeJob?.status === "queued" ? "Queued for processing" : activeJob?.phase === "preparing" ? "Preparing sampled frames for reuse" : activeJob?.phase === "collecting" ? "Reading and classifying video frames" : "Confirming round transitions"}</strong></div><span>{progress}%</span></div><Progress aria-label="Processing progress" value={progress} /><div className="progress-foot"><span>{(activeJob?.phase === "preparing" || activeJob?.phase === "collecting") ? `${activeJob.collected_samples} of ${activeJob.total_samples || "…"} frames read` : `${activeJob?.progress ?? 0} of ${activeJob?.total_samples || "…"} frames processed`}</span><span><Cpu size={13} /> {deviceLabel ? (deviceLabel === "dummy" ? "Dummy predictor" : deviceLabel === "cuda" ? "CUDA" : deviceLabel === "mps" ? "Apple Metal (MPS)" : deviceLabel === "cpu" ? "CPU fallback" : deviceLabel) : "Selecting device"}</span></div></div>}
    {latestJob?.status === "failed" && <div className="job-error"><X size={16} /><span>{latestJob.error ?? "Processing failed"}</span><UiButton variant="outline" onClick={() => process(false)}>Retry</UiButton></div>}
    {hasTimingWarning && <div className="timing-warning"><TriangleAlert size={16} /><span><strong>Playback timing warning.</strong> The nearest available frame deviated by up to {Math.round(timingError)} ms. Result clicks use the actual frame timestamps.</span></div>}
  </div>{sidebarTarget ? createPortal(sidebar, sidebarTarget) : sidebar}</>;
}

function ResultRow({ result, selected, onSelectionChange, onClick }: { result: SampleResult; selected: boolean; onSelectionChange: () => void; onClick: () => void }) {
  return <div className={`result-item ${selected ? "selected" : ""}`}><label className="result-selection" title={`Include round ${result.class_label} in export`}><UiCheckbox  checked={selected} aria-label={`Include round ${result.class_label} in export`} onCheckedChange={onSelectionChange} /></label><UiButton variant={selected ? "secondary" : "outline"} className="result-row h-auto whitespace-normal justify-start" onClick={onClick}><span className="result-class-badge">{result.class_label}</span><span className="result-confidence">{Math.round(result.confidence * 100)}% confidence</span><span className="result-jump"><Play size={12} fill="currentColor" /> Jump</span></UiButton></div>;
}

export default App;
