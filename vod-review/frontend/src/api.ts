export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type BoundingBox = {
  x: number;
  y: number;
  width: number;
  height: number;
  frame_time: number;
};

export type SampleResult = {
  timestamp_seconds: number;
  scheduled_timestamp_seconds: number;
  timing_error_ms: number;
  class_label: string;
  confidence: number;
};

export type RoundExportClip = {
  label: string;
  start_seconds: number;
  end_seconds: number;
};

export type Job = {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  progress: number;
  total_samples: number;
  collected_samples: number;
  batch_size: number;
  sample_interval_seconds: number;
  reuse_cached_crops: boolean;
  source_job_id: string | null;
  phase: "queued" | "preparing" | "collecting" | "processing" | "completed" | "failed";
  max_timing_error_ms: number | null;
  device: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  results: SampleResult[];
};

export type VideoRecord = {
  id: string;
  original_name: string;
  mime_type: string;
  duration: number;
  width: number;
  height: number;
  created_at: string;
  box: BoundingBox | null;
  current_job: Job | null;
  active_job: Job | null;
  latest_job: Job | null;
};

export type Replay = {
  id: string;
  platform: "youtube" | "twitch";
  title: string;
  creator: string;
  url: string;
  source_url: string;
  thumbnail_url: string | null;
  duration_seconds: number | null;
  published_at: string | null;
};

export type ReplayDiscovery = {
  replays: Replay[];
  errors: { source_url: string; message: string }[];
};

export type PlaybackStatus = {
  status: "preparing" | "ready" | "failed";
  manifest_url: string | null;
  error: string | null;
};

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map((issue: { msg?: string }) => issue.msg ?? "Invalid input").join("; ")
      : payload.detail;
    throw new Error(detail ?? "Request failed");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const listVideos = () => request<VideoRecord[]>("/api/videos");
export const discoverReplays = (sources: string[]) => request<ReplayDiscovery>("/api/replays/discover", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ sources }),
});
export const getVideo = (id: string) => request<VideoRecord>(`/api/videos/${id}`);
export const deleteVideo = (id: string) => request<void>(`/api/videos/${id}`, { method: "DELETE" });
export const videoContentUrl = (id: string) => `${API_BASE}/api/videos/${id}/content`;
export const getPlaybackStatus = (id: string) => request<PlaybackStatus>(`/api/videos/${id}/playback`);
export const retryPlayback = (id: string) => request<PlaybackStatus>(`/api/videos/${id}/playback`, { method: "POST" });
export const playbackManifestUrl = (path: string) => `${API_BASE}${path}`;

export async function downloadRoundExport(id: string, gameNumber: number, clips: RoundExportClip[]): Promise<Blob> {
  const response = await fetch(`${API_BASE}/api/videos/${id}/round-export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ game_number: gameNumber, clips }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(payload.detail ?? "Round export failed");
  }
  return response.blob();
}

export async function uploadVideo(file: File): Promise<VideoRecord> {
  const body = new FormData();
  body.append("file", file);
  return request<VideoRecord>("/api/videos", { method: "POST", body });
}

export type TranscriptionTask = { task_id: string; video_id: string | null; status: "queued" | "running" | "completed" | "failed"; transcript: string | null; language: string | null; error: string | null };
export type DownloadTask = { task_id: string; status: "queued" | "running" | "pausing" | "paused" | "completed" | "failed" | "dismissed"; progress: number; video?: VideoRecord | null; error?: string | null; media_type?: "video" | "audio"; transcription_task_id?: string | null; transcription?: TranscriptionTask | null };
export type DownloadQuality = "480p" | "720p" | "1080p" | "best";
export type DownloadMediaType = "video" | "audio";

export type ReplaySchedule = {
  enabled: boolean; sources: string[]; daily_time: string; timezone: string;
  window_hours: number; quality: DownloadQuality; transcribe: boolean;
};
export type ReplayAutomationRun = {
  id: string; status: string; scheduled_at: string; window_start: string;
  started_at: string; finished_at: string | null; matched: number; imported: number;
  skipped: number; transcribed: number; errors: { source_url: string; message: string }[];
};
export type ReplayAutomationStatus = {
  configured: boolean;
  settings: ReplaySchedule; next_run_at: string | null; runs: ReplayAutomationRun[];
  imports: { media_id: string; title: string; source_url: string; url: string;
    status: string; progress: number | null; error: string | null; video_id: string | null;
    transcription_task_id: string | null; transcription_status: TranscriptionTask["status"] | null;
    transcription_error: string | null }[];
};
export const getReplayAutomation = () => request<ReplayAutomationStatus>("/api/replay-automation");
export const saveReplayAutomation = (settings: ReplaySchedule) => request<ReplayAutomationStatus>("/api/replay-automation", {
  method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings),
});
export const runReplayAutomation = () => request<{ run_id: string; status: string }>("/api/replay-automation/run", { method: "POST" });
export const getVideoTranscription = (videoId: string) => request<TranscriptionTask | null>(`/api/videos/${videoId}/transcription`);

export const getDownloadTask = (taskId: string) => request<DownloadTask>(`/api/downloads/${taskId}`);
export const getResumableDownload = () => request<DownloadTask | null>("/api/resumable-download");

export const pauseDownload = (taskId: string) => request<DownloadTask>(`/api/downloads/${taskId}/pause`, { method: "POST" });
export const resumeDownload = (taskId: string) => request<DownloadTask>(`/api/downloads/${taskId}/resume`, { method: "POST" });
export const savePausedDownload = (taskId: string) => request<DownloadTask>(`/api/downloads/${taskId}/save`, { method: "POST" });
export const dismissPausedDownload = (taskId: string) => request<void>(`/api/downloads/${taskId}/dismiss`, { method: "POST" });

export const importVideoUrl = (url: string, startSeconds?: number, endSeconds?: number, checkpointIntervalSeconds?: number, quality: DownloadQuality = "720p", targetFps?: number, mediaType: DownloadMediaType = "video", transcribe = false) =>
  request<DownloadTask>("/api/videos/from-url", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, start_seconds: startSeconds, end_seconds: endSeconds, checkpoint_interval_seconds: checkpointIntervalSeconds, quality, target_fps: targetFps, media_type: mediaType, transcribe }),
  });

export const startTranscription = (videoId: string) => request<TranscriptionTask>(`/api/videos/${videoId}/transcription`, { method: "POST" });
export const getTranscription = (taskId: string) => request<TranscriptionTask>(`/api/transcriptions/${taskId}`);

export const saveBox = (id: string, box: BoundingBox) =>
  request<VideoRecord>(`/api/videos/${id}/bounding-box`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(box),
  });

export const startProcessing = (id: string, batchSize: number, sampleIntervalSeconds: number, reuseCachedCrops = false) =>
  request<Job>(`/api/videos/${id}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ batch_size: batchSize, sample_interval_seconds: sampleIntervalSeconds, reuse_cached_crops: reuseCachedCrops }),
  });

export type DriveUploadOptions = { key_rounds_only: boolean; offset_seconds: number; duration_seconds: number };

export type DriveUploadJob = {
  options?: DriveUploadOptions;
  id: string;
  status: "running" | "completed" | "failed";
  completed: number;
  total: number;
  error: string | null;
  folder_url: string | null;
};

/** Start or retry all confirmed round clips, using server-held timestamps. */
export const uploadRoundsToDrive = (id: string, options: DriveUploadOptions) => request<DriveUploadJob>(`/api/videos/${id}/gdrive-upload`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(options) });
/** Recover the current batch when the user returns to a video. */
export const getDriveUpload = (id: string) => request<DriveUploadJob | null>(`/api/videos/${id}/gdrive-upload`);
export const connectDriveUrl = `${API_BASE}/api/gdrive/connect`;

/** Read saved Google authorization without exposing server credentials. */
export const getDriveConnection = () => request<{ connected: boolean }>("/api/gdrive/status");
