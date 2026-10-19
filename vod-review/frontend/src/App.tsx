import { UploadButton } from "@/components/shared/upload-button";
import { Progress } from "@/components/ui/progress";
import { Modal } from "@/components/shared/modal";
import { Button as UiButton } from "@/components/ui/button";
import { Input as UiInput } from "@/components/ui/input";
import { Alert as UiAlert } from "@/components/ui/alert";
import { NativeSelect as UiNativeSelect } from "@/components/ui/native-select";
import { Checkbox as UiCheckbox } from "@/components/ui/checkbox";
import { PointerEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight, Circle, Cpu, Crosshair, ExternalLink, Film, ListVideo, LoaderCircle, Pause, Play, Plus, RefreshCcw, Save, ScanSearch, SlidersHorizontal, Trash2, TriangleAlert, X } from "lucide-react";
import { API_BASE, BoundingBox, deleteVideo, dismissPausedDownload, discoverReplays, DownloadTask, downloadRoundExport, getDownloadTask, getResumableDownload, getReplayAutomation, getVideoTranscription, getVideo, importVideoUrl, listVideos, pauseDownload, Replay, ReplayAutomationStatus, resumeDownload, RoundExportClip, saveBox, savePausedDownload, SampleResult, startProcessing, startTranscription, TranscriptionTask, uploadVideo, VideoRecord } from "./api";
import { TranscriptTools } from "./TranscriptTools";
import { TwitchPlayer } from "./TwitchPlayer";
import { YouTubePlayer, PlayerAdapter } from "./YouTubePlayer";
import { importOnlineVideo, setVideoMode, downloadOfflineVideo, getVideoFrame, getOfflineDownload } from "./api";
import DriveUpload from "./DriveUpload";
import ReplayAutomation from "./ReplayAutomation";
import { AddVideoDialog, AddVideoRequest, isOnlineUrl } from "./AddVideoDialog";
import { InProgressItem, ReplaySwitcher } from "./ReplaySwitcher";
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

/** Display compact OCR labels ("32") as stage-round ("3-2"). */
export function formatRoundLabel(label: string): string {
  const round = parseRoundLabel(label);
  return round ? `${round.stage}-${round.round}` : label;
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
const SEEN_VIDEOS_STORAGE_KEY = "vod-seen-videos";

function loadReplaySources(): string[] {
  try {
    const saved = JSON.parse(window.localStorage.getItem(REPLAY_SOURCES_STORAGE_KEY) ?? "[]");
    return Array.isArray(saved) ? saved.filter((source): source is string => typeof source === "string") : [];
  } catch {
    return [];
  }
}

/** Opened-video ids; null on first run so the existing library is not all marked new. */
function loadSeenVideos(): Set<string> | null {
  try {
    const raw = window.localStorage.getItem(SEEN_VIDEOS_STORAGE_KEY);
    if (raw === null) return null;
    const saved = JSON.parse(raw);
    return new Set(Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : []);
  } catch {
    return null;
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

/** h:mm:ss for long VODs, m:ss otherwise. */
function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  if (whole < 3600) return formatDuration(whole);
  return `${Math.floor(whole / 3600)}:${String(Math.floor(whole / 60) % 60).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
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

function readSelection(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}

function saveSelection(key: string, value: string | null) {
  try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch { /* Optional preferences. */ }
}

const ACTIVE_DOWNLOAD_STATUSES = new Set(["queued", "running", "pausing", "paused"]);

function App() {
  const [videos, setVideos] = useState<VideoRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => readSelection("vod-selected-video"));
  const [selected, setSelected] = useState<VideoRecord | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<VideoRecord | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [addVideoOpen, setAddVideoOpen] = useState(false);
  const [addVideoUrl, setAddVideoUrl] = useState("");
  const [switcherOpen, setSwitcherOpen] = useState(false);
  const [seenVideos, setSeenVideos] = useState<Set<string> | null>(loadSeenVideos);
  const [automationImports, setAutomationImports] = useState<ReplayAutomationStatus["imports"]>([]);
  const [transcription, setTranscription] = useState<TranscriptionTask | null>(null);
  const [transcriptPreview, setTranscriptPreview] = useState<TranscriptionTask | null>(null);
  const [savedAudio, setSavedAudio] = useState<TranscriptionTask | null>(null);
  const selectedIdentity = useRef(selectedId);
  selectedIdentity.current = selectedId;
  const [transcribing, setTranscribing] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState(0);
  const [downloadTask, setDownloadTask] = useState<DownloadTask | null>(null);
  const [downloadCheckpoints, setDownloadCheckpoints] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [automationOpen, setAutomationOpen] = useState(false);
  const [replaySources, setReplaySources] = useState<string[]>(loadReplaySources);
  const [replays, setReplays] = useState<Replay[] | null>(null);
  const [replayErrors, setReplayErrors] = useState<{ source_url: string; message: string }[]>([]);
  const [discoveringReplays, setDiscoveringReplays] = useState(false);
  const [selectedReplayCreator, setSelectedReplayCreator] = useState("all");

  const refreshAutomation = useCallback(async () => {
    const result = await getReplayAutomation();
    setAutomationImports(Array.isArray(result?.imports) ? result.imports : []);
    return result;
  }, []);

  useEffect(() => {
    let cancelled = false;
    void refreshAutomation().then((result) => {
      if (!cancelled && result?.settings && (result.configured || result.settings.sources.length)) setReplaySources(result.settings.sources);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [refreshAutomation]);

  const refreshVideos = useCallback(async () => {
    const records = await listVideos();
    setVideos(records);
    // First run: treat the existing library as already seen so only later imports read as new.
    setSeenVideos((current) => current ?? new Set(records.map((record) => record.id)));
    const saved = readSelection("vod-selected-video");
    if (saved && !records.some(record => record.id === saved)) setSelectedId(current => current === saved ? null : current);
    return records;
  }, []);

  useEffect(() => {
    refreshVideos().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load videos")).finally(() => setLoading(false));
  }, [refreshVideos]);

  useEffect(() => {
    // Automatic imports can finish in the backend while this persistent view is idle.
    const refresh = () => {
      void refreshVideos().catch(() => undefined);
      void refreshAutomation().catch(() => undefined);
    };
    const timer = window.setInterval(refresh, 15000);
    window.addEventListener("focus", refresh);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [refreshVideos, refreshAutomation]);

  useEffect(() => { saveSelection("vod-selected-video", selectedId); }, [selectedId]);
  useEffect(() => {
    if (!selectedId) return;
    setSeenVideos((current) => current?.has(selectedId) ? current : new Set([...(current ?? []), selectedId]));
  }, [selectedId]);
  useEffect(() => {
    if (!seenVideos) return;
    try { window.localStorage.setItem(SEEN_VIDEOS_STORAGE_KEY, JSON.stringify([...seenVideos])); } catch { /* New markers are a convenience. */ }
  }, [seenVideos]);
  useEffect(() => {
    const saved = readSelection("vod-audio-transcript");
    if (!saved) return;
    let cancelled = false;
    void fetch(`${API_BASE}/api/transcriptions/${saved}`).then(response => response.ok ? response.json() : null).then(task => { if (!cancelled && task && !task.video_id) setSavedAudio(task); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
  useEffect(() => {
    const task = downloadTask?.media_type === "audio" ? downloadTask.transcription : null;
    if (task?.status === "completed") { setSavedAudio(task); saveSelection("vod-audio-transcript", task.task_id); }
  }, [downloadTask]);

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
    setTranscriptPreview(null);
    setTranscribing(false);
  }, [selectedId]);

  useEffect(() => {
    if (!selectedId || transcribing) return;
    let cancelled = false;
    const refresh = async () => {
      try {
        const task = await getVideoTranscription(selectedId);
        if (!cancelled) setTranscription(task);
      } catch { /* Preserve the displayed transcript during transient refresh errors. */ }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [selectedId, transcribing]);

  const handleUpload = async (file: File) => {
    setError(null);
    setUploading(true);
    try {
      const record = await uploadVideo(file);
      setVideos((current) => [record, ...current.filter((video) => video.id !== record.id)]);
      setSelectedId(record.id);
      setAddVideoOpen(false);
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setUploading(false);
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

  const trackDownload = (task: DownloadTask) => {
    setDownloading(true);
    void pollDownload(task)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not download this video"))
      .finally(() => setDownloading(false));
  };

  useEffect(() => {
    getResumableDownload().then((task) => {
      if (!task) return;
      setDownloadTask(task);
      setDownloadProgress(task.progress);
      if (task.status !== "paused") trackDownload(task);
    }).catch(() => {});
    // This recovery check intentionally runs once when the app opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** Start a manual import; resolves with an error message for the dialog, or null once it is underway. */
  const handleAddVideo = async (request: AddVideoRequest): Promise<string | null> => {
    setError(null);
    try {
      if (request.kind === "stream" && isOnlineUrl(request.url)) {
        finishDownload(await importOnlineVideo(request.url, request.startSeconds ?? undefined, request.endSeconds ?? undefined));
        setAddVideoOpen(false);
        return null;
      }
      const audioOnly = request.kind === "audio";
      setDownloadProgress(0);
      setDownloadCheckpoints(!audioOnly && request.checkpointSeconds !== null);
      const task = await importVideoUrl(request.url, request.startSeconds ?? undefined, request.endSeconds ?? undefined, request.checkpointSeconds ?? undefined, request.quality, request.fps ?? undefined, audioOnly ? "audio" : "video", audioOnly);
      setDownloadProgress(task.progress ?? 0);
      setAddVideoOpen(false);
      trackDownload(task);
      return null;
    } catch (reason: unknown) {
      return reason instanceof Error ? reason.message : "Could not add this video";
    }
  };

  const handleTranscribeVideo = async () => {
    if (!selected) return;
    setError(null);
    const videoId = selected.id;
    setTranscribing(true);
    try {
      const task = await startTranscription(videoId);
      if (selectedIdentity.current !== videoId) return;
      setTranscription(task);
      if (task.status === "failed") setError(task.error ?? "Transcription failed");
    } catch (reason: unknown) {
      if (selectedIdentity.current === videoId) setError(reason instanceof Error ? reason.message : "Could not transcribe this video");
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

  const openSettings = () => setAutomationOpen(true);

  const saveReplaySources = useCallback((sources: string[]) => {
    // The backend owns saved sources; browser storage seeds older installations.
    try { window.localStorage.setItem(REPLAY_SOURCES_STORAGE_KEY, JSON.stringify(sources)); } catch { /* Backend settings remain saved. */ }
    setReplaySources(sources);
    setReplays(null);
    setSelectedReplayCreator("all");
    setReplayErrors([]);
  }, []);

  const handleFindReplays = async () => {
    setSwitcherOpen(false);
    if (replaySources.length === 0) {
      openSettings();
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
    setAddVideoUrl(replay.url);
    setAddVideoOpen(true);
    setReplays(null);
  };

  const openAddVideo = () => { setAddVideoUrl(""); setAddVideoOpen(true); };

  const manualTaskActive = Boolean(downloadTask && ACTIVE_DOWNLOAD_STATUSES.has(downloadTask.status));
  const inProgress = useMemo<InProgressItem[]>(() => {
    const items: InProgressItem[] = [];
    if (downloadTask && manualTaskActive) {
      items.push({
        id: downloadTask.task_id,
        title: downloadTask.video?.original_name ?? (downloadTask.media_type === "audio" ? "Audio transcript" : "Manual download"),
        stage: downloadTask.status === "paused" ? "Paused" : downloadTask.transcription?.status === "running" ? "Transcribing" : "Downloading",
        progress: downloadProgress,
        videoId: null,
      });
    }
    for (const item of automationImports) {
      const transcribingImport = item.transcription_status === "queued" || item.transcription_status === "running";
      if ((item.status === "completed" || item.status === "failed") && !transcribingImport) continue;
      items.push({
        id: item.media_id,
        title: item.title,
        stage: item.status === "completed" ? "Transcribing" : item.status === "downloading" ? "Downloading" : "Queued",
        progress: item.status === "completed" ? null : item.progress,
        videoId: item.video_id,
      });
    }
    return items;
  }, [automationImports, downloadTask, downloadProgress, manualTaskActive]);

  const unseen = useMemo(() => new Set(seenVideos ? videos.filter((video) => !seenVideos.has(video.id)).map((video) => video.id) : []), [videos, seenVideos]);

  const downloadLabel = !downloadTask ? "" : downloadTask.status === "paused" ? "Download paused" : downloadTask.status === "pausing" ? "Pausing after this checkpoint…" : downloadTask.transcription?.status === "running" ? (downloadTask.transcription.progress > 0 ? "Transcribing audio…" : "Preparing speech recognition…") : downloadTask.media_type === "audio" ? "Downloading audio…" : downloadProgress >= 95 ? "Preparing your VOD…" : "Downloading your VOD…";
  const audioResult = downloadTask?.media_type === "audio" && !manualTaskActive ? downloadTask : null;

  return (
    <div className="app-shell">
      <header className="topbar review-topbar">
        <div className="brand-mark" aria-hidden="true"><ScanSearch size={18} strokeWidth={2.4} /></div>
        <ReplaySwitcher
          videos={videos}
          selected={selected}
          unseen={unseen}
          inProgress={inProgress}
          loading={loading}
          open={switcherOpen}
          onOpenChange={setSwitcherOpen}
          onSelect={selectVideo}
          onFindReplays={() => void handleFindReplays()}
          findingReplays={discoveringReplays}
          extraAction={savedAudio && downloadTask?.transcription?.task_id !== savedAudio.task_id ? <button type="button" onClick={() => { setSwitcherOpen(false); setTranscriptPreview(savedAudio); }}>View latest audio transcript</button> : null}
        />
        <div className="topbar-spacer" />
        <UiButton variant="outline" size="icon" type="button" aria-label="Sources and automatic imports" title="Sources and automatic imports" onClick={openSettings}><SlidersHorizontal size={17} /></UiButton>
        <UiButton variant="outline" type="button" onClick={openAddVideo}><Plus size={16} />Add video</UiButton>
      </header>

      {(manualTaskActive || audioResult) && downloadTask && <div className="activity-bar" role="status" aria-label={manualTaskActive ? `${downloadTask.transcription?.status === "running" ? "Download and transcription" : "Download"} progress: ${Math.round(downloadProgress)} percent` : "Audio transcript"}>
        {manualTaskActive ? <>
          <span className="activity-bar-label">{downloadLabel}</span>
          <Progress className="activity-bar-progress" aria-label={downloadTask.transcription?.status === "running" ? "Download and transcription progress" : "Download progress"} value={downloadProgress} />
          <strong>{Math.round(downloadProgress)}%</strong>
          {downloadTask.status === "paused" ? <>
            <UiButton variant="outline" size="sm" type="button" onClick={() => void handleUsePausedDownload()}><Film size={13} /> Use saved footage</UiButton>
            <UiButton variant="outline" size="sm" type="button" onClick={() => void handleResumeDownload()}><Play size={13} /> Resume</UiButton>
            <UiButton variant="outline" size="sm" type="button" onClick={() => void handleDismissPausedDownload()}><X size={13} /> Dismiss</UiButton>
          </> : downloadTask.media_type !== "audio" && downloadCheckpoints && <UiButton variant="outline" size="sm" type="button" disabled={downloadTask.status === "pausing"} onClick={() => void handlePauseDownload()}><Pause size={13} /> {downloadTask.status === "pausing" ? "Pause requested" : "Pause"}</UiButton>}
        </> : audioResult && <>
          <span className="activity-bar-label">{audioResult.status === "failed" ? (audioResult.transcription?.error ?? audioResult.error ?? "Audio transcription failed") : audioResult.transcription?.status === "completed" ? `Transcription complete${audioResult.transcription.language ? ` · ${audioResult.transcription.language}` : ""}` : "Downloading and transcribing audio…"}</span>
          {audioResult.transcription?.status === "completed" && <UiButton variant="outline" size="sm" type="button" onClick={() => setTranscriptPreview(audioResult.transcription ?? null)}>View transcript</UiButton>}
          <UiButton variant="ghost" size="sm" type="button" aria-label="Dismiss audio transcript notice" onClick={() => setDownloadTask(null)}><X size={14} /></UiButton>
        </>}
      </div>}

      {error && <UiAlert variant="destructive" className="toast error-toast"><X size={16} /> {error}<UiButton variant="outline" onClick={() => setError(null)} aria-label="Dismiss error">Dismiss</UiButton></UiAlert>}
      {transcriptPreview && <Modal title="Transcript" className="sm:max-w-3xl" onOpenChange={() => setTranscriptPreview(null)}>
        <div className="settings-modal-heading"><h2>Transcript</h2><UiButton variant="outline" type="button" aria-label="Close transcript" onClick={() => setTranscriptPreview(null)}><X size={17} /></UiButton></div>
        <TranscriptTools key={transcriptPreview.task_id} title={transcriptPreview.video_id ? (selected?.original_name ?? "Transcript") : "Audio transcript"} transcription={transcriptPreview} />
      </Modal>}
      {automationOpen && <ReplayAutomation sources={replaySources} onClose={() => setAutomationOpen(false)} onSourcesSaved={saveReplaySources} onImported={() => { void refreshVideos().catch(() => undefined); void refreshAutomation().catch(() => undefined); }} />}
      {addVideoOpen && <AddVideoDialog initialUrl={addVideoUrl} uploading={uploading} blockedReason={manualTaskActive || downloading ? "Finish or dismiss the current download before adding another link." : null} onSubmit={handleAddVideo} onUpload={handleUpload} onClose={() => setAddVideoOpen(false)} />}

      {deleteTarget && <Modal title="Delete saved VOD?" destructive onOpenChange={() => { if (!deleting) setDeleteTarget(null); }}><div className="confirm-modal-icon"><Trash2 size={19} /></div><h2 id="delete-video-title">Delete saved VOD?</h2><p>“{deleteTarget.original_name}” and its analysis data will be permanently removed from this machine.</p><div className="confirm-modal-actions"><UiButton variant="outline" className="secondary-button" type="button" onClick={() => setDeleteTarget(null)} disabled={deleting}>Cancel</UiButton><UiButton variant="destructive" className="danger-button" type="button" onClick={() => void handleDeleteVideo()} disabled={deleting}>{deleting ? <LoaderCircle className="spin" size={14} /> : <Trash2 size={14} />}{deleting ? "Deleting…" : "Delete VOD"}</UiButton></div></Modal>}

      {replays !== null && <section className="replay-panel" aria-labelledby="new-replays-title"><div className="replay-panel-heading"><div><p className="eyebrow">DISCOVERED FROM {replaySources.length} {replaySources.length === 1 ? "SOURCE" : "SOURCES"}</p><h2 id="new-replays-title">New replays</h2></div><UiButton variant="outline" type="button" aria-label="Close new replays" onClick={() => { setReplays(null); setSelectedReplayCreator("all"); }}><X size={17} /></UiButton></div>{replays.length === 0 ? <div className="replay-empty"><ListVideo size={21} /><span>No recent videos or VODs were found.</span></div> : <><label className="replay-creator-filter">Creator<UiNativeSelect aria-label="Filter replays by creator" value={selectedReplayCreator} onChange={(event) => setSelectedReplayCreator(event.target.value)}><option value="all">All creators</option>{[...new Set(replays.map((replay) => replay.creator))].sort((a, b) => a.localeCompare(b)).map((creator) => <option key={creator} value={creator}>{creator}</option>)}</UiNativeSelect></label><div className="replay-list">{replays.filter((replay) => selectedReplayCreator === "all" || replay.creator === selectedReplayCreator).map((replay) => <article className="replay-card" key={replay.id}>{replay.thumbnail_url ? <img src={replay.thumbnail_url} alt="" /> : <div className={`replay-thumbnail ${replay.platform}`}><Play size={20} /></div>}<div className="replay-card-copy"><span className={`platform-pill ${replay.platform}`}>{replay.platform === "youtube" ? "YouTube" : "Twitch"}</span><h3>{replay.title}</h3><p>{replay.creator} · {formatReplayDate(replay.published_at)}{replay.duration_seconds ? ` · ${formatDuration(replay.duration_seconds)}` : ""}</p></div><UiButton variant="outline" className="secondary-button" type="button" onClick={() => useReplay(replay)}>Use replay</UiButton></article>)}</div></>}{replayErrors.length > 0 && <div className="replay-source-errors" role="status"><TriangleAlert size={14} /><span>{replayErrors.length} {replayErrors.length === 1 ? "source could" : "sources could"} not be checked. Open settings to review the URLs.</span></div>}</section>}

      <main className="review-main" id="workspace-panel" aria-label="Round analysis">
        {selected ? <Analyzer key={selected.id} video={selected} transcription={transcription?.video_id === selected.id ? transcription : null} transcribing={transcribing} onTranscribe={() => void handleTranscribeVideo()} onDelete={() => setDeleteTarget(selected)} onOpenTranscript={setTranscriptPreview} onUpdate={(record) => { setSelected(record); setVideos((current) => current.map((item) => item.id === record.id ? record : item)); }} onError={setError} /> : (
          <div className="welcome-state">
            <div className="welcome-icon"><Film size={28} /></div>
            <h2>Find the moment that matters.</h2>
            {loading ? <p><LoaderCircle className="spin" size={14} /> Loading library…</p>
              : videos.length === 0 ? <><p><strong>No videos yet.</strong> Add creator sources and new replays are imported, analyzed and transcribed automatically. You can also add a single video.</p><div className="welcome-actions"><UiButton type="button" onClick={openSettings}><SlidersHorizontal size={16} />Set up sources</UiButton><UiButton variant="outline" type="button" onClick={openAddVideo}><Plus size={16} />Add video</UiButton></div></>
              : <><p>Pick a replay to review its games, skip between rounds and skim the transcript.</p><div className="welcome-actions"><UiButton type="button" onClick={() => setSwitcherOpen(true)}><ListVideo size={16} />Browse replays</UiButton><UploadButton onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) void handleUpload(file); }} disabled={uploading}>{uploading ? <LoaderCircle className="spin" size={16} /> : <Plus size={16} />}{uploading ? "Uploading…" : "Upload a file"}</UploadButton></div></>}
          </div>
        )}
      </main>
    </div>
  );
}

/** Keep sampling defaults separate when switching analysis strategies. */
function initialAnalysisInterval(video: VideoRecord): number {
  const mode = video.mode ?? "offline";
  const fallback = mode === "online" ? 10 : 1;
  return (video.latest_job?.strategy ?? "offline") === mode
    ? video.latest_job?.sample_interval_seconds ?? fallback
    : fallback;
}

function Analyzer({ video, transcription, transcribing, onTranscribe, onDelete, onOpenTranscript, onUpdate, onError }: { video: VideoRecord; transcription: TranscriptionTask | null; transcribing: boolean; onTranscribe: () => void; onDelete: () => void; onOpenTranscript: (task: TranscriptionTask) => void; onUpdate: (video: VideoRecord) => void; onError: (message: string) => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const initialSeekPending = useRef(true);
  const pendingSeek = useRef<{ time: number; play: boolean } | null>(null);
  const online = video.mode === "online";
  const youtubeRef = useRef<PlayerAdapter>(null);
  const OnlinePlayer = video.source_id?.startsWith("twitch:") ? TwitchPlayer : YouTubePlayer;
  const playback = useOptimizedPlayback(video.id, videoRef, !online);
  const [preview, setPreview] = useState<string | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [conversion, setConversion] = useState<DownloadTask | null>(null);
  const [switching, setSwitching] = useState(false);
  const previewRef = useRef<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => () => { if (previewRef.current) URL.revokeObjectURL(previewRef.current); }, [video.id]);
  const overlayRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [draftBox, setDraftBox] = useState<BoundingBox | null>(video.box);
  const [boxEditing, setBoxEditing] = useState(false);
  const [drawing, setDrawing] = useState<Point | null>(null);
  const [currentTime, setCurrentTime] = useState(video.box?.frame_time ?? 0);
  const wasPlayingWhenHidden = useRef(false);
  const [saving, setSaving] = useState(false);
  const [starting, setStarting] = useState(false);
  const [analysisInterval, setAnalysisInterval] = useState(String(initialAnalysisInterval(video)));
  const [batchSize, setBatchSize] = useState(video.latest_job?.batch_size ?? 64);
  const [offsetSeconds, setOffsetSeconds] = useState("0");
  const [selectedGameIndex, setSelectedGameIndex] = useState(0);
  const [showAllRounds, setShowAllRounds] = useState(false);
  const [selectedRoundKeys, setSelectedRoundKeys] = useState<Set<string>>(new Set());
  const [exportingRounds, setExportingRounds] = useState(false);
  const [railTab, setRailTab] = useState<"rounds" | "transcript">(() => readSelection("vod-review-rail-tab") === "transcript" ? "transcript" : "rounds");
  useEffect(() => { saveSelection("vod-review-rail-tab", railTab); }, [railTab]);
  const [settingsOpen, setSettingsOpen] = useState(() => video.current_job?.status !== "completed");
  const [copied, setCopied] = useState(false);

  const activeJob = video.active_job;
  const currentJob = video.current_job;
  const latestJob = video.latest_job ?? currentJob;
  const isProcessing = activeJob?.status === "queued" || activeJob?.status === "running";
  const conversionBusy = switching || conversion?.status === "paused";
  const results = online && isProcessing && activeJob?.results?.length ? activeJob.results : currentJob?.results ?? [];
  const games = useMemo(() => groupRoundTransitions(results), [results]);
  const selectedGameResults = games[selectedGameIndex]?.results ?? [];
  const selectedGameEnd = games[selectedGameIndex + 1]?.results[0]?.timestamp_seconds ?? video.duration;
  const featuredResults = selectedGameResults.filter((result) => isFeaturedRound(result.class_label));
  const hiddenRoundCount = selectedGameResults.length - featuredResults.length;
  const visibleResults = showAllRounds ? selectedGameResults : featuredResults;
  const selectedRoundCount = selectedGameResults.filter((result) => selectedRoundKeys.has(resultKey(result))).length;
  const parsedOffset = Number(offsetSeconds);
  const position = currentTime - (Number.isFinite(parsedOffset) ? parsedOffset : 0);
  const currentResult = useMemo(() => {
    let found: SampleResult | null = null;
    for (const result of results) {
      if (result.timestamp_seconds <= position + 0.5) found = result;
      else break;
    }
    return found;
  }, [results, position]);
  const currentGameIndex = currentResult ? games.findIndex((game) => game.results.includes(currentResult)) : -1;
  const navRounds = useMemo(() => games.flatMap((game, gameIndex) => (showAllRounds ? game.results : game.results.filter((result) => isFeaturedRound(result.class_label))).map((result) => ({ result, gameIndex }))), [games, showAllRounds]);
  const nextRound = navRounds.find((item) => item.result.timestamp_seconds > position + 1) ?? null;
  const previousRound = [...navRounds].reverse().find((item) => item.result.timestamp_seconds < position - 2) ?? null;

  useEffect(() => {
    initialSeekPending.current = true;
  }, [video.id, online]);

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
    setBatchSize(video.latest_job?.batch_size ?? 64);
    setOffsetSeconds("0");
    setSelectedGameIndex(0);
    setShowAllRounds(false);
  }, [video.id]);

  useEffect(() => {
    setAnalysisInterval(String(initialAnalysisInterval(video)));
  }, [video.id, online]);

  // The round list follows playback into the next game; picking a game tab without seeking does not snap back.
  useEffect(() => {
    if (currentGameIndex >= 0) setSelectedGameIndex(currentGameIndex);
  }, [currentGameIndex]);

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
    context.fillText("ROUND REGION", x + 8, Math.max(y - 8, 15));
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
    if (!analysisInterval.trim() || !Number.isFinite(interval) || interval < (online ? 1 : 0) || interval > 3600) {
      onError(online ? "Enter an online scan interval from 1 to 3600 seconds." : "Enter an analysis interval from 0 to 3600 seconds; 0 analyzes every frame.");
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

  const seek = (time: number, play = false) => {
    const clamped = getSeekTimestamp(time, 0, video.duration);
    if (online) youtubeRef.current?.seek(clamped, play);
    else if (videoRef.current) {
      if (videoRef.current.readyState === 0) pendingSeek.current = { time: clamped, play };
      else { initialSeekPending.current = false; videoRef.current.currentTime = clamped; if (play) void videoRef.current.play().catch(() => undefined); }
    }
    setCurrentTime(clamped);
  };
  const jumpTo = (result: SampleResult) => {
    seek(getSeekTimestamp(result.timestamp_seconds, Number.isFinite(parsedOffset) ? parsedOffset : 0, video.duration), true);
  };
  const goToRound = (item: { result: SampleResult; gameIndex: number }) => {
    setSelectedGameIndex(item.gameIndex);
    jumpTo(item.result);
  };
  const skipPlayback = (seconds: number) => seek((online ? youtubeRef.current?.currentTime() ?? currentTime : videoRef.current?.currentTime ?? currentTime) + seconds);
  const toggleDrawing = async () => {
    setDrawing(null);
    if (boxEditing) { setBoxEditing(false); return; }
    if (!online) { setBoxEditing(true); return; }
    youtubeRef.current?.pause();
    setPreviewLoading(true);
    try {
      const frame = await getVideoFrame(video.id, youtubeRef.current?.currentTime() ?? currentTime);
      if (!mounted.current) { URL.revokeObjectURL(frame.url); return; }
      if (previewRef.current) URL.revokeObjectURL(previewRef.current);
      previewRef.current = frame.url;
      setPreview(frame.url);
      setCurrentTime(frame.timestamp);
      setBoxEditing(true);
    } catch (reason) { onError(reason instanceof Error ? reason.message : "Could not fetch a preview frame"); }
    finally { setPreviewLoading(false); }
  };
  const trackConversion = async (initial: DownloadTask) => {
    let task = initial;
    if (!mounted.current) return;
    setConversion(task);
    while (["queued", "running", "pausing"].includes(task.status)) {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
      if (!mounted.current) return;
      task = await getDownloadTask(task.task_id);
      if (!mounted.current) return;
      setConversion(task);
    }
    if (task.status === "paused") return;
    if (task.status !== "completed") throw new Error(task.error ?? "Download did not complete. Online playback is still available; retry Offline.");
    const ready = task.video ?? await getVideo(video.id);
    if (!mounted.current) return;
    setBoxEditing(false);
    onUpdate(ready);
    setConversion(null);
  };
  useEffect(() => {
    let cancelled = false;
    void getOfflineDownload(video.id).then(async (task) => {
      if (cancelled || task?.target_video_id !== video.id) return;
      setSwitching(true);
      try { await trackConversion(task); }
      catch (reason) { if (!cancelled) onError(reason instanceof Error ? reason.message : "Could not restore offline download"); }
      finally { if (!cancelled) setSwitching(false); }
    }).catch(() => undefined);
    return () => { cancelled = true; };
    // Resume discovery is tied to review selection, not changing progress callbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [video.id]);
  const resumeConversion = async () => {
    if (!conversion) return;
    setSwitching(true);
    try { await trackConversion(await resumeDownload(conversion.task_id)); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "Could not resume offline download"); }
    finally { setSwitching(false); }
  };
  const dismissConversion = async () => {
    if (!conversion) return;
    try { await dismissPausedDownload(conversion.task_id); setConversion(null); }
    catch (reason) { onError(reason instanceof Error ? reason.message : "Could not dismiss offline download"); }
  };
  const changeMode = async (mode: "online" | "offline") => {
    if (mode === (video.mode ?? "offline")) return;
    setSwitching(true);
    try {
      if (mode === "offline" && !video.local_available) {
        await trackConversion(await downloadOfflineVideo(video.id));
        return;
      }
      setBoxEditing(false);
      const updated = await setVideoMode(video.id, mode);
      if (!mounted.current) return;
      onUpdate(updated);
      setConversion(null);
    } catch (reason) { onError(reason instanceof Error ? reason.message : "Could not change playback mode"); }
    finally { setSwitching(false); }
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

  const copyTranscript = async () => {
    try {
      await navigator.clipboard.writeText(transcription?.transcript ?? "");
      setCopied(true);
      window.setTimeout(() => { if (mounted.current) setCopied(false); }, 2000);
    } catch { onError("Could not copy the transcript"); }
  };

  const hasBox = Boolean(video.box);
  const analyzed = latestJob?.status === "completed";
  const progress = activeJob && activeJob.total_samples > 0
    ? Math.min(100, Math.round((activeJob.phase === "preparing" ? activeJob.collected_samples / activeJob.total_samples : (activeJob.collected_samples + activeJob.progress) / (activeJob.total_samples * 2)) * 100))
    : 0;
  const deviceLabel = activeJob?.device ?? latestJob?.device;
  const timingError = currentJob?.max_timing_error_ms ?? null;
  const hasTimingWarning = timingError !== null && timingError > 100;
  const modeLocked = isProcessing || starting || conversionBusy;
  const transcriptPending = transcribing || transcription?.status === "queued" || transcription?.status === "running";
  const transcriptChip = transcriptPending ? { tone: "busy", label: `Transcribing${transcription?.progress ? ` ${Math.round(transcription.progress)}%` : "…"}` }
    : transcription?.status === "completed" ? { tone: "done", label: "Transcript ready" }
    : transcription?.status === "failed" ? { tone: "failed", label: "Transcript failed" }
    : { tone: "todo", label: online ? "No transcript · needs a local copy" : "No transcript" };
  const analysisChip = isProcessing ? { tone: "busy", label: `Analyzing ${progress}%` }
    : analyzed ? { tone: "done", label: `Analyzed · ${games.length} ${games.length === 1 ? "game" : "games"}` }
    : latestJob?.status === "failed" ? { tone: "failed", label: "Analysis failed" }
    : { tone: "todo", label: "Not analyzed" };
  const chipIcon = (tone: string) => tone === "done" ? <Check size={11} strokeWidth={3} /> : tone === "busy" ? <LoaderCircle className="spin" size={11} /> : tone === "failed" ? <X size={11} strokeWidth={3} /> : <Circle size={9} />;
  const processLabel = isProcessing ? `${activeJob?.phase === "scanning" ? "Scanning" : activeJob?.phase === "refining" ? "Refining" : activeJob?.phase === "preparing" ? "Preparing" : "Analyzing"} ${progress}%` : analyzed ? "Analyze again" : latestJob?.status === "failed" ? "Retry analysis" : "Process video";
  const intervalNumber = Number(analysisInterval);
  const analysisSummary = [
    intervalNumber > 0 ? `${online ? "Scans" : "Samples"} every ${analysisInterval} s` : "Every frame",
    analyzed && timingError !== null ? `PTS ±${Math.round(timingError)} ms` : null,
    !hasBox ? "Draw the round region to start" : null,
  ].filter(Boolean).join(" · ");
  const percent = (seconds: number) => `${Math.max(0, Math.min(100, (seconds / Math.max(1, video.duration)) * 100))}%`;
  const driveDisabledReason = online ? "Switch to a local copy to upload round clips." : isProcessing ? "Round classification is still running. Upload becomes available when round starts are ready." : currentJob?.status === "completed" ? "No round starts were detected. Check the round region and process the video again." : "Process this video to detect round starts before uploading.";

  return <div className="analyzer">
    <div className="review-status">
      <span className={`status-chip tone-${hasBox ? "done" : "todo"}`}>{chipIcon(hasBox ? "done" : "todo")}{hasBox ? "Round region set" : "Round region needed"}</span>
      <span className={`status-chip tone-${analysisChip.tone}`}>{chipIcon(analysisChip.tone)}{analysisChip.label}</span>
      <button type="button" className={`status-chip tone-${transcriptChip.tone}`} onClick={() => setRailTab("transcript")}>{chipIcon(transcriptChip.tone)}{transcriptChip.label}</button>
      <span className="review-status-spacer" />
      <span className="video-meta"><span>{video.width} × {video.height}</span><span>{formatClock(video.duration)}</span></span>
      <UiButton variant="ghost" size="icon-sm" type="button" aria-label={`Delete ${video.original_name}`} title="Delete this VOD" onClick={onDelete}><Trash2 size={15} /></UiButton>
    </div>

    <div className="review-layout">
      <section className="review-player" aria-label="Player">
        <div className="video-stage-wrap">
          <div className="video-stage" ref={overlayRef} style={{ aspectRatio: `${video.width} / ${video.height}` }}>
            {online && video.source_id ? <OnlinePlayer ref={youtubeRef} sourceId={video.source_id} start={video.source_start_seconds ?? 0} duration={video.duration} initialTime={currentTime} onTime={(time) => { if (!boxEditing) setCurrentTime(time); }} onError={onError} /> : <video ref={videoRef} controls playsInline preload="metadata" onPause={(event) => { setCurrentTime(event.currentTarget.currentTime); }} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} onLoadedMetadata={(event) => { if (!initialSeekPending.current) return; initialSeekPending.current = false; const queued = pendingSeek.current; const initialTime = queued?.time ?? currentTime; pendingSeek.current = null; event.currentTarget.currentTime = initialTime; setCurrentTime(initialTime); if (queued?.play) void event.currentTarget.play().catch(() => undefined); }} />}
            {online && boxEditing && preview && <img className="online-frame-preview" src={preview} alt="Still frame for drawing the round crop" />}
            {!online && playback.status === "preparing" && <div className="playback-status"><LoaderCircle className="spin" size={18} /><strong>Preparing fast playback…</strong><span>This one-time step makes startup and scrubbing responsive.</span></div>}
            {!online && playback.status === "failed" && playback.error && <div className="playback-warning"><span>{playback.error ?? "Optimized playback is unavailable."}</span><UiButton variant="outline" type="button" onClick={() => void playback.retry()}>Retry</UiButton></div>}
            <canvas ref={canvasRef} className={`box-canvas ${boxEditing ? "is-editing" : ""}`} onPointerDown={handlePointerDown} onPointerMove={handlePointerMove} onPointerUp={handlePointerUp} onPointerCancel={handlePointerUp} aria-label="Draw a bounding box on the video" />
            {boxEditing && !draftBox && <div className="canvas-hint"><span>+</span><strong>Draw the round region</strong><small>Click and drag over the round number</small></div>}
            {currentResult && !boxEditing && <span className="video-round-badge">{games.length > 1 && currentGameIndex >= 0 ? `Game ${currentGameIndex + 1} · ` : ""}Round <b>{formatRoundLabel(currentResult.class_label)}</b></span>}
          </div>
        </div>

        <div className="round-timeline">
          <div className="round-timeline-head"><span>{games.length > 1 ? "Click a game to jump to it" : results.length ? "Round timeline" : "Current frame"}</span><span className="mono">{formatClock(currentTime)} / {formatClock(video.duration)}</span></div>
          {results.length > 0 && <div className="round-timeline-track">
            {games.map((game, index) => {
              const start = game.results[0]?.timestamp_seconds ?? 0;
              const end = games[index + 1]?.results[0]?.timestamp_seconds ?? video.duration;
              return <button key={game.number} type="button" className="round-timeline-game" aria-pressed={index === selectedGameIndex} aria-label={`Jump to game ${game.number}`} style={{ left: percent(start), width: percent(end - start) }} onClick={() => { setSelectedGameIndex(index); if (game.results[0]) jumpTo(game.results[0]); }}>{games.length > 1 ? `Game ${game.number}` : ""}</button>;
            })}
            {visibleResults.map((result) => <span key={resultKey(result)} className={`round-timeline-tick ${result === currentResult ? "is-current" : ""}`} style={{ left: percent(result.timestamp_seconds) }} aria-hidden="true" />)}
            <span className="round-timeline-playhead" style={{ left: percent(position) }} aria-hidden="true" />
          </div>}
        </div>

        <div className="review-controls">
          <UiButton variant="outline" type="button" aria-label="Rewind 5 seconds" onClick={() => skipPlayback(-5)}>−5s</UiButton>
          <UiButton variant="outline" type="button" aria-label="Skip forward 5 seconds" onClick={() => skipPlayback(5)}>+5s</UiButton>
          {results.length > 0 && <>
            <span className="review-controls-divider" aria-hidden="true" />
            <UiButton variant="outline" type="button" disabled={!previousRound} onClick={() => previousRound && goToRound(previousRound)}><ChevronLeft size={16} />{previousRound ? `Previous · ${formatRoundLabel(previousRound.result.class_label)}` : "Previous round"}</UiButton>
            <UiButton type="button" disabled={!nextRound} onClick={() => nextRound && goToRound(nextRound)}>{nextRound ? `Next · ${formatRoundLabel(nextRound.result.class_label)}` : "Last round"}<ChevronRight size={16} /></UiButton>
          </>}
          <span className="review-controls-spacer" />
          <UiButton variant={boxEditing ? "secondary" : "outline"} type="button" aria-pressed={boxEditing} disabled={previewLoading || conversionBusy || isProcessing} onClick={() => void toggleDrawing()}>{previewLoading ? <LoaderCircle className="spin" size={16} /> : <Crosshair size={16} />}{boxEditing ? "Exit drawing" : hasBox ? "Edit box" : "Draw box"}</UiButton>
          {(boxEditing || !hasBox || draftBox !== video.box) && <UiButton variant="outline" type="button" disabled={!draftBox || saving || conversionBusy || isProcessing} onClick={saveCurrentBox}>{saving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}{saving ? "Saving…" : hasBox ? "Update box" : "Save box"}</UiButton>}
          {video.source_id && <div className="segmented" role="group" aria-label="Review playback mode">
            <button type="button" aria-pressed={online} disabled={modeLocked} onClick={() => void changeMode("online")}>Streaming</button>
            <button type="button" aria-pressed={!online} disabled={modeLocked} onClick={() => void changeMode("offline")}>Local copy</button>
          </div>}
        </div>
        {switching && <p className="analysis-note" role="status">{conversion ? `Downloading a local copy… ${Math.round(conversion.progress)}%` : "Switching playback…"} Streaming stays available until the copy is ready.</p>}
        {conversion?.status === "paused" && <div className="inline-notice" role="status"><span>Local copy download paused. Resume or dismiss it before changing playback or analyzing.</span><UiButton variant="outline" size="sm" disabled={switching} onClick={() => void resumeConversion()}>Resume offline download</UiButton><UiButton variant="outline" size="sm" disabled={switching} onClick={() => void dismissConversion()}>Dismiss offline download</UiButton></div>}
        {online && <p className="analysis-note">Streaming: round clips and new transcripts need a local copy. Coarse scans may miss rounds shorter than the scan interval.</p>}

        <section className="analysis-bar" aria-label="Analysis">
          <div className="analysis-bar-head">
            <strong>Analysis</strong>
            <span className="analysis-bar-summary">{analysisSummary}</span>
            <span className="review-controls-spacer" />
            <UiButton variant="outline" size="sm" type="button" aria-expanded={settingsOpen} aria-controls={`analysis-settings-${video.id}`} onClick={() => setSettingsOpen((open) => !open)}><SlidersHorizontal size={14} />Settings</UiButton>
            <UiButton variant={analyzed ? "outline" : "default"} size="sm" type="button" disabled={!hasBox || isProcessing || starting || conversionBusy} onClick={() => process(false)}>{isProcessing ? <LoaderCircle className="spin" size={14} /> : <Play size={14} />}{processLabel}</UiButton>
          </div>
          {settingsOpen && <div className="analysis-settings" id={`analysis-settings-${video.id}`}>
            <label className="analysis-field" title="Elapsed time between analyzed frames. 0 checks every frame.">{online ? "Scan every (seconds)" : "Sample every (seconds)"}<UiInput aria-label="Analysis interval in seconds" type="number" min={online ? "1" : "0"} max="3600" step="any" value={analysisInterval} disabled={isProcessing || starting || conversionBusy} onChange={(event) => setAnalysisInterval(event.target.value)} /></label>
            <label className="analysis-field">Batch size<UiInput aria-label="Batch size" type="number" min="1" max="256" value={batchSize} disabled={isProcessing || starting || conversionBusy} onChange={(event) => setBatchSize(Math.max(1, Math.min(256, Number(event.target.value) || 1)))} /></label>
            {analyzed && <UiButton variant="outline" type="button" className="analysis-rerun" disabled={isProcessing || starting || conversionBusy} onClick={() => process(true)}><RefreshCcw size={15} /> Rerun OCR</UiButton>}
            <p className="analysis-note">{intervalNumber > 0 ? `About ${Math.ceil(video.duration / intervalNumber).toLocaleString()} samples for this video. ` : "Every-frame mode: all source frames will be prepared and analyzed. "}{online ? "Candidate changes are refined at one-second intervals." : "Sampled frames are cached, so reruns are faster."}</p>
          </div>}
          {isProcessing && <div className="progress-card"><div className="progress-copy"><div><span className="eyebrow">{activeJob?.sample_interval_seconds === 0 ? "EVERY FRAME" : `EVERY ${activeJob?.sample_interval_seconds} SECONDS`} · BATCH SIZE {activeJob?.batch_size}</span><strong>{activeJob?.status === "queued" ? "Queued for processing" : activeJob?.phase === "scanning" ? "Scanning remote round samples" : activeJob?.phase === "refining" ? "Refining candidate round changes" : activeJob?.phase === "preparing" ? "Preparing sampled frames for reuse" : activeJob?.phase === "collecting" ? "Reading and classifying video frames" : "Confirming round transitions"}</strong></div><span>{progress}%</span></div><Progress aria-label="Processing progress" value={progress} /><div className="progress-foot"><span>{(activeJob?.phase === "preparing" || activeJob?.phase === "collecting") ? `${activeJob.collected_samples} of ${activeJob.total_samples || "…"} frames read` : `${activeJob?.progress ?? 0} of ${activeJob?.total_samples || "…"} frames processed`}</span><span><Cpu size={13} /> {deviceLabel ? (deviceLabel === "dummy" ? "Dummy predictor" : deviceLabel === "cuda" ? "CUDA" : deviceLabel === "mps" ? "Apple Metal (MPS)" : deviceLabel === "cpu" ? "CPU fallback" : deviceLabel) : "Selecting device"}</span></div></div>}
          {latestJob?.status === "failed" && <div className="job-error"><X size={16} /><span>{latestJob.error ?? "Processing failed"}</span><UiButton variant="outline" onClick={() => process(false)}>Retry</UiButton></div>}
          {hasTimingWarning && <div className="timing-warning"><TriangleAlert size={16} /><span><strong>Playback timing warning.</strong> The nearest available frame deviated by up to {Math.round(timingError)} ms. Round jumps use the actual frame timestamps.</span></div>}
        </section>
      </section>

      <aside className="review-rail" aria-label="Review tools">
        <div className="review-rail-tabs" role="tablist" aria-label="Review tools">
          <button type="button" role="tab" id={`rail-rounds-${video.id}`} aria-selected={railTab === "rounds"} aria-controls={`rail-panel-${video.id}`} onClick={() => setRailTab("rounds")}>Rounds</button>
          <button type="button" role="tab" id={`rail-transcript-${video.id}`} aria-selected={railTab === "transcript"} aria-controls={`rail-panel-${video.id}`} onClick={() => setRailTab("transcript")}>Transcript</button>
        </div>
        <div className="review-rail-panel" id={`rail-panel-${video.id}`} role="tabpanel" aria-labelledby={`rail-${railTab}-${video.id}`}>
          {railTab === "rounds" ? <>
            {results.length > 0 && <div className="rounds-toolbar">
              {games.length > 1 && <div className="segmented" role="group" aria-label="Game">{games.map((game, index) => <button key={game.number} type="button" aria-pressed={index === selectedGameIndex} title={`${game.results.length} rounds`} onClick={() => setSelectedGameIndex(index)}>Game {game.number}</button>)}</div>}
              <span className="review-controls-spacer" />
              {hiddenRoundCount > 0 && <label className="rounds-toggle"><UiCheckbox checked={showAllRounds} onCheckedChange={(checked) => setShowAllRounds(checked === true)} aria-label="Show all rounds" />All rounds</label>}
              <label className="rounds-offset" title="Shift every round jump earlier (negative) or later (positive).">Jump offset (s)<UiInput aria-label="Seek offset in seconds" type="number" step="1" value={offsetSeconds} onChange={(event) => setOffsetSeconds(event.target.value)} /></label>
            </div>}
            {results.length === 0 ? <div className="results-empty"><span>{isProcessing ? "Rounds appear here as they are found." : hasBox ? "Process the video to find round changes." : "Draw and save the round region, then process the video."}</span></div>
              : <ul className="round-list">{visibleResults.map((result) => <ResultRow key={resultKey(result)} result={result} playing={result === currentResult} selected={selectedRoundKeys.has(resultKey(result))} onSelectionChange={() => toggleRoundSelection(result)} onClick={() => jumpTo(result)} />)}</ul>}
            {selectedGameResults.length > 0 && <div className="rail-footer">
              <span>{selectedRoundCount} {selectedRoundCount === 1 ? "round" : "rounds"} selected</span>
              <span className="review-controls-spacer" />
              <UiButton variant="outline" size="sm" type="button" disabled={online || conversionBusy || selectedRoundCount === 0 || exportingRounds} title={online ? "Switch to a local copy to export round clips" : undefined} onClick={() => void exportSelectedRounds()}>{exportingRounds ? <LoaderCircle className="spin" size={13} /> : <Film size={13} />}{exportingRounds ? "Building video…" : `Download selected (${selectedRoundCount})`}</UiButton>
            </div>}
            {results.length > 0 && <details className="rail-details"><summary>Upload clips to Google Drive</summary><DriveUpload key={video.id} videoId={video.id} offsetSeconds={offsetSeconds} onOffsetChange={setOffsetSeconds} enabled={!online && currentJob?.status === "completed" && results.length > 0} disabledReason={driveDisabledReason} /></details>}
          </> : <>
            <TranscriptTools title={video.original_name} videoId={video.id} transcription={transcription} online={online} transcribing={transcribing} onTranscribe={onTranscribe} onSeek={seek} showTitle={false} />
            {transcription?.status === "completed" && <div className="rail-footer">
              <UiButton variant="outline" size="sm" type="button" disabled={!transcription.transcript} onClick={() => void copyTranscript()}>{copied ? <Check size={13} /> : null}{copied ? "Copied" : "Copy transcript"}</UiButton>
              <UiButton variant="outline" size="sm" type="button" onClick={() => onOpenTranscript(transcription)}>Open full transcript<ExternalLink size={13} /></UiButton>
            </div>}
          </>}
        </div>
      </aside>
    </div>
  </div>;
}

function ResultRow({ result, selected, playing, onSelectionChange, onClick }: { result: SampleResult; selected: boolean; playing: boolean; onSelectionChange: () => void; onClick: () => void }) {
  const label = formatRoundLabel(result.class_label);
  return <li className={`round-row ${playing ? "is-playing" : ""}`}>
    <UiCheckbox checked={selected} aria-label={`Include round ${result.class_label} in export`} onCheckedChange={onSelectionChange} />
    <span className="round-row-label">{label}</span>
    <span className="round-row-meta">{playing ? "Playing" : `${Math.round(result.confidence * 100)}% match`}</span>
    <UiButton variant="outline" size="sm" type="button" className="round-row-jump" aria-label={`Jump to round ${label} at ${formatClock(result.timestamp_seconds)}`} onClick={onClick}>{formatClock(result.timestamp_seconds)}</UiButton>
  </li>;
}

export default App;
