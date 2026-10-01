"""FastAPI service for persistent video analysis."""

from __future__ import annotations

import asyncio
import json
import math
import mimetypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from round_classifier.predict import get_ocr_classifier
from round_classifier.config import load_round_labels

try:
    from . import db, frame_cache
    from .shared_transcripts import publish_completed_transcripts
    from .constants import (
        DEFAULT_BATCH_SIZE,
        MAX_COLLECTION_PROGRESS_UPDATES,
        PROGRESS_WRITE_INTERVAL_SECONDS,
        SAMPLE_INTERVAL_SECONDS,
    )
    from .models import BoundingBox, DownloadQuality, ReplayDiscoveryRequest, ProcessingRequest, RoundExportClip, RoundExportRequest, VideoUrlRequest
except ImportError:  # Running with `uvicorn app:app` from the backend directory.
    import frame_cache
    import db
    from shared_transcripts import publish_completed_transcripts
    from constants import DEFAULT_BATCH_SIZE, MAX_COLLECTION_PROGRESS_UPDATES, PROGRESS_WRITE_INTERVAL_SECONDS, SAMPLE_INTERVAL_SECONDS
    from models import BoundingBox, DownloadQuality, ReplayDiscoveryRequest, ProcessingRequest, RoundExportClip, RoundExportRequest, VideoUrlRequest

try:
    from .processor import process_cached_crops, process_video_all_frames
    from .tracing import configure_performance_logging, set_trace_context, trace_event, trace_resources
except ImportError:  # Running with `uvicorn app:app` from the backend directory.
    from processor import process_cached_crops, process_video_all_frames
    from tracing import configure_performance_logging, set_trace_context, trace_event, trace_resources


WORKERS: ThreadPoolExecutor | None = None
PLAYBACK_TASKS: dict[str, asyncio.Task[None]] = {}
PLAYBACK_ERRORS: dict[str, str] = {}
DOWNLOAD_TASKS: dict[str, asyncio.Task[None]] = {}
DOWNLOAD_PAUSE_REQUESTS: set[str] = set()
ROOT = Path(__file__).resolve().parent.parent
SAVE_PROCESSED_FRAMES = os.environ.get("VOD_SAVE_FRAMES", "").lower() in {"1", "true", "yes", "on"}
SAVE_PROCESSED_BOXES = os.environ.get("VOD_SAVE_BOXES", "").lower() in {"1", "true", "yes", "on"}
FRAMES_DIR = Path(os.environ.get("VOD_FRAMES_DIR", ROOT / "frames"))
BOXES_DIR = Path(os.environ.get("VOD_BOXES_DIR", ROOT / "boxes"))
OCR_CACHE_DIR = Path(os.environ["VOD_OCR_CACHE_DIR"]) if "VOD_OCR_CACHE_DIR" in os.environ else None


class TemporaryVideoResponse(Response):
    """Stream a generated video and remove its temporary directory afterward."""

    media_type = "video/mp4"

    def __init__(self, path: Path, filename: str, cleanup_directory: Path) -> None:
        self.path = path
        self.cleanup_directory = cleanup_directory
        super().__init__(
            content=None,
            media_type=self.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Content-Length": str(path.stat().st_size),
            },
        )

    async def __call__(self, scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": self.status_code, "headers": self.raw_headers})
        try:
            with self.path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
            await send({"type": "http.response.body", "body": b"", "more_body": False})
        finally:
            shutil.rmtree(self.cleanup_directory, ignore_errors=True)


class DownloadPaused(Exception):
    """Raised after the latest completed checkpoint when a pause was requested."""

    def __init__(self, video: dict[str, Any]) -> None:
        super().__init__("Download paused")
        self.video = video


def ocr_cache_dir() -> Path:
    return OCR_CACHE_DIR or db.DATA_DIR / "ocr_cache"


def is_supported_video_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"}:
        return False
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in ("youtube.com", "youtu.be", "twitch.tv"))


def is_replay_source_url(value: str) -> bool:
    """Accept YouTube channel pages and Twitch streamer home pages, not individual videos."""
    parsed = urlparse(value.strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    path_parts = [part for part in parsed.path.split("/") if part]
    if parsed.scheme not in {"http", "https"} or parsed.query or parsed.fragment:
        return False
    if hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        if not path_parts:
            return False
        return path_parts[0].startswith("@") or (
            path_parts[0] in {"channel", "c", "user"} and len(path_parts) >= 2
        )
    if hostname == "twitch.tv" or hostname.endswith(".twitch.tv"):
        return len(path_parts) == 1 and path_parts[0].lower() not in {"videos", "directory", "downloads", "settings"}
    return False


def replay_discovery_url(source: str) -> str:
    parsed = urlparse(source.strip())
    hostname = (parsed.hostname or "").lower()
    base = source.strip().rstrip("/")
    if hostname == "youtube.com" or hostname.endswith(".youtube.com"):
        if parsed.path.rstrip("/").split("/")[-1] not in {"videos", "streams"}:
            return f"{base}/videos"
    if hostname == "twitch.tv" or hostname.endswith(".twitch.tv"):
        return f"{base}/videos?filter=archives&sort=time"
    return base


def _replay_timestamp(entry: dict[str, Any]) -> int | None:
    raw_timestamp = entry.get("timestamp") or entry.get("release_timestamp")
    if isinstance(raw_timestamp, (int, float)):
        return int(raw_timestamp)
    upload_date = entry.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8 and upload_date.isdigit():
        try:
            parsed = datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            return int(parsed.timestamp())
        except ValueError:
            return None
    return None


def discover_replays_for_source(source: str, limit: int = 12) -> list[dict[str, Any]]:
    """Fetch a shallow, metadata-only list of recent uploads for one source."""
    if not is_replay_source_url(source):
        raise HTTPException(status_code=400, detail="Enter YouTube channel or Twitch streamer home page URLs")
    command = [
        sys.executable, "-m", "yt_dlp", "--flat-playlist", "--playlist-end", str(limit),
        "--quiet", "--no-warnings", "--skip-download", "--dump-single-json", "--",
        replay_discovery_url(source),
    ]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=True, timeout=45)
        payload = json.loads(completed.stdout)
    except FileNotFoundError as exc:
        raise RuntimeError("yt-dlp is not installed on the server") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("The source took too long to respond") from exc
    except subprocess.CalledProcessError as exc:
        detail_lines = [line.strip() for line in (exc.stderr or "").splitlines() if line.strip()]
        raise RuntimeError(detail_lines[-1][:300] if detail_lines else "The source could not be read") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("The source returned unreadable metadata") from exc

    platform = "youtube" if "youtube.com" in (urlparse(source).hostname or "").lower() else "twitch"
    result: list[dict[str, Any]] = []
    for entry in (payload.get("entries") or [])[:limit]:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        replay_url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
        if not isinstance(replay_url, str) or not replay_url.startswith(("http://", "https://")):
            replay_url = (
                f"https://www.youtube.com/watch?v={entry['id']}"
                if platform == "youtube"
                else f"https://www.twitch.tv/videos/{entry['id']}"
            )
        timestamp = _replay_timestamp(entry)
        thumbnail = entry.get("thumbnail")
        if not thumbnail and isinstance(entry.get("thumbnails"), list) and entry["thumbnails"]:
            thumbnail = entry["thumbnails"][-1].get("url")
        result.append({
            "id": f"{platform}:{entry['id']}",
            "platform": platform,
            "title": str(entry.get("title") or "Untitled replay"),
            "creator": str(entry.get("channel") or entry.get("uploader") or payload.get("channel") or payload.get("uploader") or "Unknown creator"),
            "url": replay_url,
            "source_url": source,
            "thumbnail_url": thumbnail if isinstance(thumbnail, str) else None,
            "duration_seconds": entry.get("duration") if isinstance(entry.get("duration"), (int, float)) else None,
            "published_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat() if timestamp is not None else None,
        })
    return result


def probe_video(path: Path) -> dict[str, Any]:
    try:
        import av
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PyAV is not installed on the server") from exc

    try:
        container = av.open(str(path))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The uploaded file is not a readable video") from exc

    try:
        if not container.streams.video:
            raise HTTPException(status_code=400, detail="The uploaded file does not contain a video stream")
        stream = container.streams.video[0]
        format_names = set(str(container.format.name or "").lower().split(","))
        codec_name = str(stream.codec_context.name or "").lower()
        if not (format_names & {"mov", "mp4", "matroska", "webm"}) or codec_name not in {"h264", "vp8", "vp9", "av1"}:
            raise HTTPException(status_code=400, detail="Use a browser-playable H.264 MP4 or VP8/VP9/AV1 WebM video")
        stream_duration = (
            float(stream.duration * stream.time_base)
            if stream.duration is not None and stream.time_base is not None
            else 0.0
        )
        container_duration = float(container.duration / av.time_base) if container.duration else 0.0
        duration = stream_duration or container_duration
        width = int(stream.codec_context.width or 0)
        height = int(stream.codec_context.height or 0)
        if duration <= 0 or width <= 0 or height <= 0:
            raise HTTPException(status_code=400, detail="The uploaded video has invalid dimensions or duration")
        return {"duration": duration, "width": width, "height": height}
    finally:
        container.close()


def persist_video(path: Path, original_name: str, mime_type: str, video_id: str) -> dict[str, Any]:
    metadata = probe_video(path)
    return db.create_video(
        video_id,
        original_name,
        path,
        mime_type,
        metadata["duration"],
        metadata["width"],
        metadata["height"],
    )


def playback_directory(video_id: str) -> Path:
    return db.DATA_DIR / "playback" / video_id


def playback_manifest(video_id: str) -> Path:
    return playback_directory(video_id) / "index.m3u8"


def playback_is_ready(video_id: str) -> bool:
    directory = playback_directory(video_id)
    return (
        (directory / "index.m3u8").is_file()
        and (directory / "init.mp4").is_file()
        and any(directory.glob("segment-*.m4s"))
    )


def build_playback_assets(video_id: str) -> None:
    """Build an atomic, stream-copy HLS representation for responsive browser seeking."""
    source = db.video_path(video_id)
    if not source.exists():
        raise FileNotFoundError("Video file is missing")

    playback_root = db.DATA_DIR / "playback"
    playback_root.mkdir(parents=True, exist_ok=True)
    destination = playback_directory(video_id)
    temporary = Path(tempfile.mkdtemp(prefix=f".{video_id}-", dir=playback_root))
    try:
        command = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(source),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-c", "copy",
            "-sn", "-dn",
            "-hls_time", "6",
            "-hls_list_size", "0",
            "-hls_playlist_type", "vod",
            "-hls_flags", "independent_segments",
            "-hls_segment_type", "fmp4",
            "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", str(temporary / "segment-%06d.m4s"),
            str(temporary / "index.m3u8"),
        ]
        subprocess.run(command, capture_output=True, text=True, check=True)
        if not (temporary / "index.m3u8").is_file() or not (temporary / "init.mp4").is_file():
            raise RuntimeError("ffmpeg did not create a complete playback manifest")
        if not any(temporary.glob("segment-*.m4s")):
            raise RuntimeError("ffmpeg did not create any playback segments")
        if destination.exists():
            shutil.rmtree(destination)
        temporary.replace(destination)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed on the server") from exc
    except subprocess.CalledProcessError as exc:
        detail_lines = [line.strip() for line in exc.stderr.splitlines() if line.strip()]
        detail = detail_lines[-1] if detail_lines else "ffmpeg could not prepare optimized playback"
        raise RuntimeError(detail[:500]) from exc
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def start_playback_preparation(video_id: str) -> None:
    if playback_is_ready(video_id):
        return
    current = PLAYBACK_TASKS.get(video_id)
    if current is not None and not current.done():
        return

    PLAYBACK_ERRORS.pop(video_id, None)

    async def prepare() -> None:
        await asyncio.to_thread(build_playback_assets, video_id)

    task = asyncio.create_task(prepare(), name=f"prepare-playback-{video_id}")
    PLAYBACK_TASKS[video_id] = task

    def finished(completed: asyncio.Task[None]) -> None:
        if PLAYBACK_TASKS.get(video_id) is completed:
            PLAYBACK_TASKS.pop(video_id, None)
        try:
            completed.result()
        except asyncio.CancelledError:
            return
        except Exception as exc:  # noqa: BLE001 - report background preparation failures in the UI
            PLAYBACK_ERRORS[video_id] = str(exc)

    task.add_done_callback(finished)


def source_has_audio(path: Path) -> bool:
    try:
        import av
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="PyAV is not installed on the server") from exc

    container = av.open(str(path))
    try:
        return bool(container.streams.audio)
    finally:
        container.close()


def build_round_export(source: Path, output: Path, clips: list[RoundExportClip]) -> None:
    include_audio = source_has_audio(source)
    filters: list[str] = []
    if len(clips) > 1:
        video_splits = "".join(f"[vsrc{index}]" for index in range(len(clips)))
        filters.append(f"[0:v:0]split={len(clips)}{video_splits}")
        if include_audio:
            audio_splits = "".join(f"[asrc{index}]" for index in range(len(clips)))
            filters.append(f"[0:a:0]asplit={len(clips)}{audio_splits}")
    for index, clip in enumerate(clips):
        start = f"{clip.start_seconds:.6f}"
        end = f"{clip.end_seconds:.6f}"
        video_input = f"[vsrc{index}]" if len(clips) > 1 else "[0:v:0]"
        filters.append(f"{video_input}trim=start={start}:end={end},setpts=PTS-STARTPTS[v{index}]")
        if include_audio:
            audio_input = f"[asrc{index}]" if len(clips) > 1 else "[0:a:0]"
            filters.append(f"{audio_input}atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{index}]")

    if len(clips) == 1:
        video_output = "[v0]"
        audio_output = "[a0]" if include_audio else None
    elif include_audio:
        concat_inputs = "".join(f"[v{index}][a{index}]" for index in range(len(clips)))
        filters.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=1[vout][aout]")
        video_output = "[vout]"
        audio_output = "[aout]"
    else:
        concat_inputs = "".join(f"[v{index}]" for index in range(len(clips)))
        filters.append(f"{concat_inputs}concat=n={len(clips)}:v=1:a=0[vout]")
        video_output = "[vout]"
        audio_output = None

    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
        "-filter_complex", ";".join(filters), "-map", video_output,
    ]
    if audio_output is not None:
        command.extend(["-map", audio_output, "-c:a", "aac", "-b:a", "160k"])
    else:
        command.append("-an")
    command.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(output),
    ])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="ffmpeg is not installed on the server") from exc
    except subprocess.CalledProcessError as exc:
        detail_lines = [line.strip() for line in exc.stderr.splitlines() if line.strip()]
        detail = detail_lines[-1] if detail_lines else "ffmpeg could not create the round export"
        raise HTTPException(status_code=500, detail=f"Round export failed: {detail[:300]}") from exc


def _parse_ffmpeg_time(value: str) -> float | None:
    try:
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except (ValueError, TypeError):
        return None


class DownloadProgressTracker:
    """Translate yt-dlp and ffmpeg output into one monotonic download percentage."""

    def __init__(
        self,
        callback: Callable[[float], None],
        start_seconds: float | None,
        end_seconds: float | None,
    ) -> None:
        self.callback = callback
        self.start_seconds = start_seconds or 0.0
        self.end_seconds = end_seconds
        self.source_duration: float | None = None
        self.format_order: list[str] = []
        self.expected_formats = 1
        self.maximum = 0.0

    def _emit(self, percent: float) -> None:
        # Keep 100% for successful persistence; transfer/remux work tops out at 99%.
        bounded = min(99.0, max(self.maximum, percent))
        if bounded > self.maximum:
            self.maximum = bounded
            self.callback(bounded)

    def _requested_duration(self) -> float | None:
        if self.end_seconds is not None:
            return max(0.0, self.end_seconds - self.start_seconds)
        if self.source_duration is not None:
            return max(0.0, self.source_duration - self.start_seconds)
        return None

    def consume(self, line: str) -> None:
        if line.startswith("FRAMEWISE_PROGRESS="):
            fields = line.removeprefix("FRAMEWISE_PROGRESS=").split("\t", 4)
            if len(fields) != 5:
                return
            format_id, video_codec, audio_codec, duration_text, progress_text = fields
            try:
                duration = float(duration_text)
                if duration > 0:
                    self.source_duration = duration
            except ValueError:
                pass
            video_only = video_codec not in {"", "none"} and audio_codec in {"", "none"}
            audio_only = audio_codec not in {"", "none"} and video_codec in {"", "none"}
            self.expected_formats = 2 if video_only or audio_only else 1
            try:
                progress = json.loads(progress_text)
            except json.JSONDecodeError:
                return
            if format_id not in self.format_order:
                self.format_order.append(format_id)
            total = progress.get("total_bytes") or progress.get("total_bytes_estimate")
            downloaded = progress.get("downloaded_bytes")
            if total and downloaded is not None:
                fraction = min(1.0, max(0.0, float(downloaded) / float(total)))
            elif progress.get("fragment_count") and progress.get("fragment_index") is not None:
                fraction = min(1.0, max(0.0, float(progress["fragment_index"]) / float(progress["fragment_count"])))
            elif progress.get("status") == "finished":
                fraction = 1.0
            else:
                return
            phase = min(self.format_order.index(format_id), self.expected_formats - 1)
            self._emit(((phase + fraction) / self.expected_formats) * 95.0)
            return

        if line.startswith("out_time="):
            elapsed = _parse_ffmpeg_time(line.removeprefix("out_time="))
            requested_duration = self._requested_duration()
            if elapsed is not None and requested_duration and requested_duration > 0:
                self._emit(min(1.0, elapsed / requested_duration) * 95.0)


def apply_download_fps(path: Path, target_fps: float | None) -> None:
    """Normalize the saved video to the requested cadence, preserving the original on failure."""
    if target_fps is None:
        return
    if not math.isfinite(target_fps) or not 1 <= target_fps <= 120:
        raise ValueError("Target FPS must be between 1 and 120")
    converted = path.with_name(f"{path.stem}.fps-tmp.mp4")
    try:
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(path),
            "-map", "0:v:0", "-map", "0:a?", "-vf", f"fps={target_fps:g}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy", "-movflags", "+faststart", str(converted),
        ], capture_output=True, text=True, check=True)
        converted.replace(path)
    finally:
        converted.unlink(missing_ok=True)


def download_format(quality: DownloadQuality) -> str:
    if quality == "best":
        return "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/best[vcodec^=avc1][ext=mp4]/best[ext=mp4]"
    height = int(quality.removesuffix("p"))
    return (
        f"bestvideo[height<={height}][vcodec^=avc1]+bestaudio[ext=m4a]/"
        f"best[height<={height}][vcodec^=avc1][ext=mp4]/best[height<={height}][ext=mp4]"
    )


def download_video_url_local(
    url: str,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
    quality: DownloadQuality = "720p",
    target_fps: float | None = None,
) -> dict[str, Any]:
    if not is_supported_video_url(url):
        raise HTTPException(status_code=400, detail="Enter a valid Twitch or YouTube video URL")

    video_id = uuid.uuid4().hex
    saved = False
    output_template = str(db.VIDEO_DIR / f"{video_id}.%(ext)s")
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--no-simulate",
        "--format",
        download_format(quality),
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
    ]
    if start_seconds is not None or end_seconds is not None:
        range_start = start_seconds or 0
        formatted_end = "inf" if end_seconds is None else f"{end_seconds:.6f}"
        command.extend([
            "--download-sections", f"*{range_start:.6f}-{formatted_end}",
            "--force-keyframes-at-cuts",
        ])
    if progress_callback is not None:
        command.extend([
            "--no-quiet",
            "--progress",
            "--newline",
            "--color", "never",
            "--progress-template",
            "download:FRAMEWISE_PROGRESS=%(info.format_id)s\\t%(info.vcodec|none)s\\t%(info.acodec|none)s\\t%(info.duration|0)s\\t%(progress)j",
        ])
        if start_seconds is not None or end_seconds is not None:
            command.extend(["--downloader-args", "ffmpeg:-progress pipe:2 -nostats"])
    command.extend([
        "--output", output_template,
        "--print", "after_move:FRAMEWISE_PATH=%(filepath)s",
        "--print", "after_move:FRAMEWISE_TITLE=%(title)s",
        "--", url.strip(),
    ])
    try:
        if progress_callback is None:
            completed = subprocess.run(command, capture_output=True, text=True, check=True)
            output_lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        else:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            output_lines = []
            tracker = DownloadProgressTracker(progress_callback, start_seconds, end_seconds)
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                tracker.consume(line)
                if line:
                    output_lines.append(line)
            return_code = process.wait()
            if return_code:
                joined_output = "\n".join(output_lines)
                raise subprocess.CalledProcessError(return_code, command, joined_output, joined_output)

        reported_paths = [
            Path(line.removeprefix("FRAMEWISE_PATH="))
            for line in output_lines
            if line.startswith("FRAMEWISE_PATH=")
        ]
        video_directory = db.VIDEO_DIR.resolve()
        path = next(
            (
                candidate
                for candidate in reported_paths
                if candidate.resolve().parent == video_directory
                and candidate.name.startswith(f"{video_id}.")
                and candidate.is_file()
            ),
            None,
        )
        if path is None:
            candidates = [
                candidate
                for candidate in db.VIDEO_DIR.glob(f"{video_id}.*")
                if candidate.is_file()
                and candidate.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
            ]
            path = candidates[0] if len(candidates) == 1 else None
        if path is None:
            raise RuntimeError("The downloader did not produce a single video file")
        title_lines = [
            line.removeprefix("FRAMEWISE_TITLE=")
            for line in output_lines
            if line.startswith("FRAMEWISE_TITLE=")
        ]
        title = title_lines[-1] if title_lines else "Downloaded video"
        safe_title = Path(title.replace("\x00", "")).name[:180] or "Downloaded video"
        original_name = safe_title if Path(safe_title).suffix else f"{safe_title}{path.suffix}"
        apply_download_fps(path, target_fps)
        payload = persist_video(path, original_name, mimetypes.guess_type(path.name)[0] or "video/mp4", video_id)
        saved = True
        return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="yt-dlp is not installed on the server") from exc
    except subprocess.CalledProcessError as exc:
        detail_lines = [line.strip() for line in (exc.stderr or "").splitlines() if line.strip()]
        detail = detail_lines[-1] if detail_lines else "The remote video could not be downloaded"
        raise HTTPException(status_code=400, detail=f"Download failed: {detail[:300]}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Download failed: {str(exc)[:300]}") from exc
    finally:
        if not saved:
            for partial in db.VIDEO_DIR.glob(f"{video_id}.*"):
                partial.unlink(missing_ok=True)


def download_audio_url_local(url: str, task_id: str, progress_callback: Callable[[float], None] | None = None) -> Path:
    """Download source audio to the local download cache for optional transcription."""
    if not is_supported_video_url(url):
        raise HTTPException(status_code=400, detail="Enter a valid Twitch or YouTube video URL")
    output_template = str(db.DOWNLOAD_DIR / f"{task_id}.%(ext)s")
    command = [sys.executable, "-m", "yt_dlp", "--no-playlist", "--format", "bestaudio/best", "--no-quiet", "--no-warnings", "--progress", "--newline", "--color", "never", "--progress-template", "download:FRAMEWISE_PROGRESS=%(info.format_id)s\\t%(info.vcodec|none)s\\t%(info.acodec|none)s\\t%(info.duration|0)s\\t%(progress)j", "--output", output_template, "--print", "after_move:FRAMEWISE_PATH=%(filepath)s", "--", url.strip()]
    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        output_lines: list[str] = []
        tracker = DownloadProgressTracker(progress_callback, None, None) if progress_callback else None
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if tracker:
                tracker.consume(line)
            if line:
                output_lines.append(line)
        if process.wait():
            details = "\n".join(output_lines)
            raise subprocess.CalledProcessError(process.returncode or 1, command, details, details)
        candidates = [Path(line.removeprefix("FRAMEWISE_PATH=")) for line in output_lines if line.startswith("FRAMEWISE_PATH=")]
        path = next((candidate for candidate in candidates if candidate.is_file() and candidate.parent.resolve() == db.DOWNLOAD_DIR.resolve()), None)
        if path is None:
            files = [path for path in db.DOWNLOAD_DIR.glob(f"{task_id}.*") if path.is_file() and path.suffix not in {".part", ".ytdl"}]
            path = files[0] if len(files) == 1 else None
        if path is None:
            raise RuntimeError("The downloader did not produce a single audio file")
        if progress_callback:
            progress_callback(100)
        return path
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="yt-dlp is not installed on the server") from exc
    except subprocess.CalledProcessError as exc:
        detail = next((line.strip() for line in (exc.stderr or "").splitlines() if line.strip()), "The remote audio could not be downloaded")
        raise HTTPException(status_code=400, detail=f"Audio download failed: {detail[:300]}") from exc


def download_audio_url(url: str, task_id: str, progress_callback: Callable[[float], None] | None = None) -> Path:
    """Reuse suite audio or a video audio stream before the local audio downloader."""
    try:
        from .shared_media import download_shared_audio
    except ImportError:
        from shared_media import download_shared_audio

    path = download_shared_audio(url, lambda: download_audio_url_local(url, task_id, progress_callback))
    if progress_callback:
        progress_callback(100)
    return path


def _transcribe_audio_file(path: str) -> tuple[str, str | None]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="Transcription requires the optional faster-whisper dependency. Install it with `uv sync --extra transcription`.") from exc
    model = WhisperModel(os.environ.get("VOD_WHISPER_MODEL", "large-v3"), device=os.environ.get("VOD_WHISPER_DEVICE", "cuda"), compute_type=os.environ.get("VOD_WHISPER_COMPUTE_TYPE", "float16"))
    segments, info = model.transcribe(path, beam_size=5, vad_filter=True)
    transcript = "".join(segment.text for segment in segments).strip()
    return transcript, getattr(info, "language", None)


async def _run_transcription_task(task_id: str) -> None:
    db.update_transcription_task(task_id, status="running")
    try:
        connection = db.get_db()
        row = connection.execute("SELECT media_path FROM transcription_tasks WHERE id=?", (task_id,)).fetchone()
        connection.close()
        if row is None:
            return
        transcript, language = await asyncio.to_thread(_transcribe_audio_file, row["media_path"])
        db.update_transcription_task(task_id, status="completed", transcript=transcript, language=language)
    except HTTPException as exc:
        db.update_transcription_task(task_id, status="failed", error=str(exc.detail))
        return
    except Exception as exc:
        db.update_transcription_task(task_id, status="failed", error=str(exc))
        return
    await asyncio.to_thread(publish_completed_transcripts, task_id)


def _download_url_metadata(url: str) -> dict[str, Any]:
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "--skip-download",
        "--dump-single-json",
        "--",
        url.strip(),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=True)
    return json.loads(completed.stdout)


def _download_checkpoint_chunk(
    url: str,
    path_template: Path,
    start_seconds: float,
    end_seconds: float,
    progress_callback: Callable[[float], None],
    quality: DownloadQuality = "720p",
) -> Path:
    command = [
        sys.executable, "-m", "yt_dlp", "--no-playlist",
        "--format", download_format(quality),
        "--merge-output-format", "mp4", "--remux-video", "mp4", "--continue",
        "--download-sections", f"*{start_seconds:.6f}-{end_seconds:.6f}",
        "--force-keyframes-at-cuts",
        "--no-quiet", "--progress", "--newline", "--color", "never",
        "--progress-template", "download:FRAMEWISE_PROGRESS=%(progress._percent_str)s",
        "--downloader-args", "ffmpeg:-progress pipe:2 -nostats",
        "--output", str(path_template),
        "--print", "after_move:FRAMEWISE_PATH=%(filepath)s",
        "--", url.strip(),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    tracker = DownloadProgressTracker(progress_callback, start_seconds, end_seconds)
    output_lines: list[str] = []
    output_path: Path | None = None
    assert process.stdout is not None
    for raw_line in process.stdout:
        line = raw_line.strip()
        if line.startswith("FRAMEWISE_PATH="):
            output_path = Path(line.removeprefix("FRAMEWISE_PATH="))
        tracker.consume(line)
        if line:
            output_lines.append(line)
    return_code = process.wait()
    if return_code:
        joined_output = "\n".join(output_lines)
        raise subprocess.CalledProcessError(return_code, command, joined_output, joined_output)
    if output_path is None:
        candidates = sorted(path_template.parent.glob(f"{path_template.stem.split('.')[0]}*.mp4"))
        output_path = candidates[-1] if candidates else None
    if output_path is None or not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("yt-dlp did not produce a checkpoint file")
    return output_path


def _concat_download_checkpoints(parts: list[Path], destination: Path) -> None:
    manifest = destination.with_suffix(".concat.txt")
    manifest.write_text(
        "".join(f"file '{str(part.resolve()).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'\n" for part in parts),
        encoding="utf-8",
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "concat", "-safe", "0", "-i", str(manifest),
                "-c", "copy", "-movflags", "+faststart", str(destination),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        manifest.unlink(missing_ok=True)


def _publish_download_checkpoints(task_id: str, parts: list[Path], title: str, target_fps: float | None = None) -> dict[str, Any]:
    if not parts:
        raise HTTPException(status_code=409, detail="No completed checkpoints are available yet")
    checkpoint_dir = db.DOWNLOAD_DIR / task_id
    partial_id = uuid.uuid4().hex
    joined = checkpoint_dir / f"paused-{partial_id}.mp4"
    final_path = db.VIDEO_DIR / f"{partial_id}.mp4"
    _concat_download_checkpoints(parts, joined)
    shutil.copy2(joined, final_path)
    try:
        safe_title = Path(title.replace("\x00", "")).name[:160] or "Downloaded video"
        original_name = f"{Path(safe_title).stem} (paused checkpoint).mp4"
        apply_download_fps(final_path, target_fps)
        return persist_video(final_path, original_name, "video/mp4", partial_id)
    except Exception:
        final_path.unlink(missing_ok=True)
        raise
    finally:
        joined.unlink(missing_ok=True)


def download_video_url_checkpointed_local(
    task_id: str,
    url: str,
    start_seconds: float | None,
    end_seconds: float | None,
    checkpoint_interval_seconds: float,
    progress_callback: Callable[[float], None],
    should_pause: Callable[[], bool],
    quality: DownloadQuality = "720p",
    target_fps: float | None = None,
) -> dict[str, Any]:
    """Download durable time slices, then join them into the library video."""
    if not is_supported_video_url(url):
        raise HTTPException(status_code=400, detail="Enter a valid Twitch or YouTube video URL")
    try:
        metadata = _download_url_metadata(url)
        source_duration = float(metadata.get("duration") or 0)
        range_start = start_seconds or 0.0
        range_end = min(end_seconds, source_duration) if end_seconds is not None and source_duration else (end_seconds or source_duration)
        if range_end <= range_start:
            raise RuntimeError("The selected range is outside the video duration")
        checkpoint_dir = db.DOWNLOAD_DIR / task_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        chunk_count = math.ceil((range_end - range_start) / checkpoint_interval_seconds)
        parts: list[Path] = []
        for index in range(chunk_count):
            chunk_start = range_start + index * checkpoint_interval_seconds
            chunk_end = min(range_end, chunk_start + checkpoint_interval_seconds)
            template = checkpoint_dir / f"checkpoint-{index:06d}.%(ext)s"
            completed_path = checkpoint_dir / f"checkpoint-{index:06d}.mp4"
            if completed_path.is_file() and completed_path.stat().st_size > 0:
                path = completed_path
            else:
                def report_chunk(percent: float, completed=index) -> None:
                    progress_callback(((completed + percent / 100.0) / chunk_count) * 95.0)

                path = _download_checkpoint_chunk(url, template, chunk_start, chunk_end, report_chunk, quality)
                if path != completed_path:
                    path.replace(completed_path)
                    path = completed_path
            parts.append(path)
            progress_callback(((index + 1) / chunk_count) * 95.0)
            if should_pause():
                raise DownloadPaused(_publish_download_checkpoints(
                    task_id,
                    parts,
                    str(metadata.get("title") or "Downloaded video"),
                    target_fps,
                ))

        joined = checkpoint_dir / "completed.mp4"
        _concat_download_checkpoints(parts, joined)
        progress_callback(99.0)
        final_path = db.VIDEO_DIR / f"{task_id}.mp4"
        apply_download_fps(joined, target_fps)
        joined.replace(final_path)
        raw_title = str(metadata.get("title") or "Downloaded video")
        safe_title = Path(raw_title.replace("\x00", "")).name[:180] or "Downloaded video"
        original_name = safe_title if Path(safe_title).suffix else f"{safe_title}.mp4"
        payload = persist_video(final_path, original_name, "video/mp4", task_id)
        shutil.rmtree(checkpoint_dir, ignore_errors=True)
        return payload
    except DownloadPaused:
        raise
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="yt-dlp or ffmpeg is not installed on the server") from exc
    except subprocess.CalledProcessError as exc:
        detail_lines = [line.strip() for line in (exc.stderr or "").splitlines() if line.strip()]
        detail = detail_lines[-1] if detail_lines else "The remote video could not be downloaded"
        raise HTTPException(status_code=400, detail=f"Download failed: {detail[:300]}") from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Download failed: {str(exc)[:300]}") from exc


def download_video_url(
    url: str,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    progress_callback: Callable[[float], None] | None = None,
    quality: DownloadQuality = "720p",
) -> dict[str, Any]:
    """Download or reuse a shared source while retaining the existing UI contract."""
    try:
        from .shared_media import download_shared_video
    except ImportError:
        from shared_media import download_shared_video
    return download_shared_video(
        url, start_seconds, end_seconds, quality,
        lambda: download_video_url_local(url, start_seconds, end_seconds, progress_callback, quality),
    )


def download_video_url_checkpointed(
    task_id: str,
    url: str,
    start_seconds: float | None,
    end_seconds: float | None,
    checkpoint_interval_seconds: float,
    progress_callback: Callable[[float], None],
    should_pause: Callable[[], bool],
    quality: DownloadQuality = "720p",
) -> dict[str, Any]:
    """Reuse completed media or preserve the original checkpoint/pause workflow."""
    try:
        from .shared_media import download_shared_video
    except ImportError:
        from shared_media import download_shared_video
    return download_shared_video(
        url, start_seconds, end_seconds, quality,
        lambda: download_video_url_checkpointed_local(
            task_id, url, start_seconds, end_seconds, checkpoint_interval_seconds,
            progress_callback, should_pause, quality,
        ),
    )


def run_job(job_id: str) -> None:
    job_started = time.perf_counter()
    context = db.begin_job(job_id)
    if context is None:
        trace_event("job_skipped", job_id=job_id, reason="missing_job_or_video")
        return
    job, video = context
    set_trace_context(job_id=job_id, video_id=video["id"])

    trace_event(
        "job_started",
        duration_seconds=f"{video['duration']:.3f}",
        processing_mode="time_sampled_with_sliding_transitions",
        batch_size=job["batch_size"],
        sample_interval_seconds=job["sample_interval_seconds"],
        save_frames=SAVE_PROCESSED_FRAMES,
        save_boxes=SAVE_PROCESSED_BOXES,
        reuse_cached_crops=bool(job["reuse_cached_crops"]),
    )
    # Do not initialize a CUDA context before the cold-start/model-load timings.
    trace_resources("job_start", include_cuda=False)

    box = {"x": job["box_x"], "y": job["box_y"], "width": job["box_width"], "height": job["box_height"]}
    pending_results: list[tuple[float, float, str, float]] = []
    last_progress_write = time.monotonic()
    last_collected_write = 0

    def write_collection_progress(collected: int, total: int) -> None:
        nonlocal last_progress_write, last_collected_write
        now = time.monotonic()
        collection_step = max(
            1,
            (total + MAX_COLLECTION_PROGRESS_UPDATES - 1) // MAX_COLLECTION_PROGRESS_UPDATES,
        )
        if collected < total and (
            now - last_progress_write < PROGRESS_WRITE_INTERVAL_SECONDS
            or collected - last_collected_write < collection_step
        ):
            return
        db.update_collection_progress(job_id, collected, total)
        last_progress_write = now
        last_collected_write = collected

    def write_batch(
        results: list[tuple[float, float, str, float]],
        device: str,
        progress: int,
        total: int,
    ) -> None:
        nonlocal last_progress_write
        pending_results.extend(results)
        now = time.monotonic()
        if progress >= total or now - last_progress_write < PROGRESS_WRITE_INTERVAL_SECONDS:
            return
        db.update_processing_progress(job_id, progress, total, device)
        last_progress_write = now

    try:
        round_labels = load_round_labels()
        classifier = get_ocr_classifier(round_labels)
        if job["reuse_cached_crops"]:
            cache_dir = ocr_cache_dir() / str(job["source_job_id"])
            processed, device = process_cached_crops(
                cache_dir,
                job["batch_size"],
                write_batch,
                write_collection_progress,
                classifier,
                sample_interval_seconds=job["sample_interval_seconds"],
            )
        else:
            cache_dir = ocr_cache_dir() / job_id
            crop_dir = cache_dir / "crops"
            shared_frames = frame_cache.ensure(
                Path(video["path"]),
                lambda processed, total: db.update_frame_preparation(job_id, processed, total),
                sample_interval_seconds=job["sample_interval_seconds"],
            )
            # Preparation counts full frames; analysis counts only selected samples.
            db.update_collection_progress(job_id, 0, 0)
            processed, device = process_video_all_frames(
                Path(video["path"]),
                video["width"],
                video["height"],
                box,
                job["batch_size"],
                write_batch,
                write_collection_progress,
                classifier,
                frame_output_dir=FRAMES_DIR / video["id"] if SAVE_PROCESSED_FRAMES else None,
                box_images=crop_dir,
                sample_interval_seconds=job["sample_interval_seconds"],
                frame_cache=shared_frames,
            )
            crops = [
                {
                    "file": f"crops/{path.name}",
                    "timestamp": float(path.stem.split("_", 1)[1].removesuffix("s")),
                }
                for path in sorted(crop_dir.glob("*.png"))
            ]
            manifest = {"version": 2, "sample_interval_seconds": job["sample_interval_seconds"], "box": box, "crops": crops}
            temporary_manifest = cache_dir / "manifest.json.tmp"
            temporary_manifest.write_text(json.dumps(manifest), encoding="utf-8")
            temporary_manifest.replace(cache_dir / "manifest.json")
        database_started = time.perf_counter()
        db.complete_job(
            job_id,
            video["id"],
            pending_results,
            processed,
            processed,
            device,
        )
        trace_event(
            "job_completed",
            device=device,
            samples=processed,
            database_ms=f"{(time.perf_counter() - database_started) * 1000:.2f}",
            total_ms=f"{(time.perf_counter() - job_started) * 1000:.2f}",
        )
        trace_resources("job_complete")
    except Exception as exc:  # noqa: BLE001 - persist worker failures for the UI
        db.fail_job(job_id, str(exc))
        trace_event(
            "job_failed",
            error=type(exc).__name__,
            total_ms=f"{(time.perf_counter() - job_started) * 1000:.2f}",
        )
        trace_resources("job_failed")


def startup() -> None:
    global WORKERS
    configure_performance_logging()
    db.init_db()
    publish_completed_transcripts()
    if WORKERS is None:
        WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-processor")


def shutdown() -> None:
    global WORKERS
    for task in PLAYBACK_TASKS.values():
        task.cancel()
    PLAYBACK_TASKS.clear()
    DOWNLOAD_PAUSE_REQUESTS.update(DOWNLOAD_TASKS)
    for task in DOWNLOAD_TASKS.values():
        task.cancel()
    DOWNLOAD_TASKS.clear()
    if WORKERS is not None:
        WORKERS.shutdown(wait=False, cancel_futures=True)
        WORKERS = None


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own the creator scheduler and existing VOD workers for one backend lifetime."""
    startup()
    automation = None
    try:
        try:
            from .replay_automation.discovery import discover_window
            from .replay_automation.service import ReplayAutomation
        except ImportError:  # Support the documented backend-directory launch.
            from replay_automation.discovery import discover_window
            from replay_automation.service import ReplayAutomation
        automation = ReplayAutomation(discover_window, import_discovered_video)
        application.state.replay_automation = automation
        await automation.start()
        yield
    finally:
        if automation is not None:
            await automation.stop()
        application.state.replay_automation = None
        shutdown()


app = FastAPI(title="VOD Review and Round Classification", lifespan=lifespan)
try:
    from .gdrive.router import router as gdrive_router
except ImportError:  # Support the documented backend-directory launch.
    from gdrive.router import router as gdrive_router
app.include_router(gdrive_router)
try:
    from .replay_automation.router import router as replay_automation_router
except ImportError:
    from replay_automation.router import router as replay_automation_router
app.include_router(replay_automation_router)
try:
    from .media_store.router import router as shared_media_router
    from .shared_resources import router as shared_video_router
except ImportError:
    from media_store.router import router as shared_media_router
    from shared_resources import router as shared_video_router
app.include_router(shared_media_router)
app.include_router(shared_video_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/videos")
async def list_videos() -> list[dict[str, Any]]:
    return db.list_videos()


@app.post("/api/replays/discover")
async def discover_replays(request: ReplayDiscoveryRequest) -> dict[str, Any]:
    invalid_sources = [source for source in request.sources if not is_replay_source_url(source)]
    if invalid_sources:
        raise HTTPException(status_code=400, detail="Enter YouTube channel or Twitch streamer home page URLs")

    semaphore = asyncio.Semaphore(4)

    async def discover_source(source: str) -> list[dict[str, Any]]:
        async with semaphore:
            return await asyncio.to_thread(discover_replays_for_source, source)

    discovered = await asyncio.gather(
        *(discover_source(source) for source in request.sources), return_exceptions=True
    )
    replays: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for source, result in zip(request.sources, discovered, strict=True):
        if isinstance(result, BaseException):
            errors.append({"source_url": source, "message": str(result)})
        else:
            replays.extend(result)
    deduplicated = {replay["id"]: replay for replay in replays}
    ordered = sorted(
        deduplicated.values(),
        key=lambda replay: replay["published_at"] or "",
        reverse=True,
    )
    return {"replays": ordered, "errors": errors}


@app.post("/api/videos", status_code=201)
async def upload_video(file: UploadFile = File(...)) -> dict[str, Any]:
    filename = Path(file.filename or "video").name
    suffix = Path(filename).suffix.lower() or ".video"
    video_id = uuid.uuid4().hex
    path = db.VIDEO_DIR / f"{video_id}{suffix}"
    with path.open("wb") as output:
        shutil.copyfileobj(file.file, output)
    try:
        video = persist_video(path, filename, file.content_type or mimetypes.guess_type(filename)[0] or "video/mp4", video_id)
        start_playback_preparation(video_id)
        return video
    except Exception:
        path.unlink(missing_ok=True)
        raise


async def _run_download_task(task_id: str, request: VideoUrlRequest) -> None:
    db.update_download_task(task_id, status="running")
    last_persisted = -1.0
    keep_pause_request = False

    def report_progress(percent: float) -> None:
        nonlocal last_persisted
        if percent >= last_persisted + 0.25 or percent >= 99:
            db.update_download_task(task_id, progress=percent)
            last_persisted = percent

    try:
        if request.media_type == "audio":
            media_path = await asyncio.to_thread(download_audio_url, request.url, task_id, report_progress)
            transcription_task_id = None
            if request.transcribe:
                transcription_task_id = uuid.uuid4().hex
                db.create_transcription_task(transcription_task_id, str(media_path))
                db.update_download_task(task_id, media_path=str(media_path), transcription_task_id=transcription_task_id)
                await _run_transcription_task(transcription_task_id)
                transcription = db.get_transcription_task(transcription_task_id)
                if transcription["status"] == "failed":
                    raise RuntimeError(transcription["error"] or "Transcription failed")
            db.update_download_task(task_id, status="completed", progress=100, media_path=str(media_path), transcription_task_id=transcription_task_id)
            return
        if request.checkpoint_interval_seconds is not None:
            video = await asyncio.to_thread(
                download_video_url_checkpointed,
                task_id,
                request.url,
                request.start_seconds,
                request.end_seconds,
                request.checkpoint_interval_seconds,
                report_progress,
                lambda: task_id in DOWNLOAD_PAUSE_REQUESTS,
                request.quality,
                **({"target_fps": request.target_fps} if request.target_fps is not None else {}),
            )
        else:
            video = await asyncio.to_thread(
                download_video_url,
                request.url,
                request.start_seconds,
                request.end_seconds,
                report_progress,
                request.quality,
                **({"target_fps": request.target_fps} if request.target_fps is not None else {}),
            )
        start_playback_preparation(video["id"])
        db.update_download_task(task_id, status="completed", progress=100, video_id=video["id"])
    except DownloadPaused as paused:
        start_playback_preparation(paused.video["id"])
        db.update_download_task(task_id, status="paused", video_id=paused.video["id"], error=None)
    except asyncio.CancelledError:
        if request.checkpoint_interval_seconds is not None:
            keep_pause_request = True
            db.update_download_task(task_id, status="paused", error=None)
        else:
            db.update_download_task(task_id, status="failed", error="Download was interrupted")
        raise
    except Exception as exc:
        db.update_download_task(task_id, status="failed", error=str(exc))
    finally:
        if not keep_pause_request:
            DOWNLOAD_PAUSE_REQUESTS.discard(task_id)


@app.post("/api/videos/from-url", status_code=202)
async def import_video_url(request: VideoUrlRequest) -> dict[str, Any]:
    if not is_supported_video_url(request.url):
        raise HTTPException(status_code=400, detail="Enter a valid Twitch or YouTube video URL")
    task_id = uuid.uuid4().hex
    payload = db.create_download_task(
        task_id,
        url=request.url,
        start_seconds=request.start_seconds,
        end_seconds=request.end_seconds,
        checkpoint_interval_seconds=request.checkpoint_interval_seconds,
        quality=request.quality,
        target_fps=request.target_fps,
        media_type=request.media_type,
        transcribe=request.transcribe,
    )
    task = asyncio.create_task(_run_download_task(task_id, request), name=f"download-video-{task_id}")
    DOWNLOAD_TASKS[task_id] = task
    task.add_done_callback(lambda completed: DOWNLOAD_TASKS.pop(task_id, None) if DOWNLOAD_TASKS.get(task_id) is completed else None)
    return payload


async def import_discovered_video(request: VideoUrlRequest, media_id: str) -> dict[str, Any]:
    """Import scheduled media through the same tracked task and playback path as a URL upload."""
    try:
        from .replay_automation import store
    except ImportError:
        from replay_automation import store
    payload = await import_video_url(request)
    task_id = payload["task_id"]
    store.update_import(media_id, status="downloading", task_id=task_id)
    task = DOWNLOAD_TASKS.get(task_id)
    if task is not None:
        # Stopping discovery does not itself cancel an ordinary download. Backend
        # shutdown still owns cancellation of every DOWNLOAD_TASKS entry.
        await asyncio.shield(task)
    completed = db.get_download_task(task_id)
    if completed["status"] != "completed" or completed["video"] is None:
        raise RuntimeError(completed["error"] or "Scheduled video download did not complete")
    return completed["video"]


@app.post("/api/videos/{video_id}/transcription", status_code=202)
async def start_video_transcription(video_id: str) -> dict[str, Any]:
    path = db.video_path(video_id)
    task_id = uuid.uuid4().hex
    payload = db.create_transcription_task(task_id, str(path), video_id)
    task = asyncio.create_task(_run_transcription_task(task_id), name=f"transcribe-video-{task_id}")
    task.add_done_callback(lambda completed: None)
    return payload


@app.get("/api/transcriptions/{task_id}")
async def get_transcription(task_id: str) -> dict[str, Any]:
    return db.get_transcription_task(task_id)


@app.get("/api/downloads/{task_id}")
async def get_download_task(task_id: str) -> dict[str, Any]:
    return db.get_download_task(task_id)


@app.get("/api/resumable-download")
async def get_resumable_download() -> dict[str, Any] | None:
    return db.get_resumable_download_task()


@app.post("/api/downloads/{task_id}/dismiss", status_code=204)
async def dismiss_download_task(task_id: str) -> None:
    db.dismiss_download_task(task_id)


@app.post("/api/downloads/{task_id}/pause", status_code=202)
async def pause_download_task(task_id: str) -> dict[str, Any]:
    payload = db.get_download_task(task_id)
    request_data = db.get_download_request(task_id)
    if request_data["checkpoint_interval_seconds"] is None:
        raise HTTPException(status_code=409, detail="Set a checkpoint interval to pause and resume this download")
    if payload["status"] not in {"queued", "running", "pausing"}:
        raise HTTPException(status_code=409, detail="Only an active download can be paused")
    DOWNLOAD_PAUSE_REQUESTS.add(task_id)
    db.update_download_task(task_id, status="pausing")
    return db.get_download_task(task_id)


@app.post("/api/downloads/{task_id}/resume", status_code=202)
async def resume_download_task(task_id: str) -> dict[str, Any]:
    payload = db.get_download_task(task_id)
    if payload["status"] not in {"paused", "failed"}:
        raise HTTPException(status_code=409, detail="Only a paused or interrupted download can be resumed")
    request_data = db.get_download_request(task_id)
    if request_data["checkpoint_interval_seconds"] is None:
        raise HTTPException(status_code=409, detail="This download has no resumable checkpoints")
    request = VideoUrlRequest(**request_data)
    DOWNLOAD_PAUSE_REQUESTS.discard(task_id)
    db.update_download_task(task_id, status="queued", error="")
    task = asyncio.create_task(_run_download_task(task_id, request), name=f"download-video-{task_id}")
    DOWNLOAD_TASKS[task_id] = task
    task.add_done_callback(lambda completed: DOWNLOAD_TASKS.pop(task_id, None) if DOWNLOAD_TASKS.get(task_id) is completed else None)
    return db.get_download_task(task_id)


@app.post("/api/downloads/{task_id}/save", status_code=201)
async def save_paused_download(task_id: str) -> dict[str, Any]:
    payload = db.get_download_task(task_id)
    if payload["status"] != "paused":
        raise HTTPException(status_code=409, detail="Only a paused download can be saved")
    if payload["video"] is not None:
        return payload
    checkpoint_dir = db.DOWNLOAD_DIR / task_id
    parts = sorted(checkpoint_dir.glob("checkpoint-*.mp4"))
    request_data = db.get_download_request(task_id)
    metadata = await asyncio.to_thread(_download_url_metadata, request_data["url"])
    video = await asyncio.to_thread(
        _publish_download_checkpoints,
        task_id,
        parts,
        str(metadata.get("title") or "Downloaded video"),
        request_data["target_fps"],
    )
    start_playback_preparation(video["id"])
    db.update_download_task(task_id, video_id=video["id"], error=None)
    return db.get_download_task(task_id)


@app.delete("/api/videos/{video_id}", status_code=204)
async def delete_video(video_id: str) -> None:
    task = PLAYBACK_TASKS.pop(video_id, None)
    if task is not None and not task.done():
        task.cancel()
    PLAYBACK_ERRORS.pop(video_id, None)
    shared_media = db.video_is_shared(video_id)
    path = db.delete_video(video_id)
    if not shared_media:
        path.unlink(missing_ok=True)
        frame_cache.remove(path)
    shutil.rmtree(playback_directory(video_id), ignore_errors=True)


@app.get("/api/videos/{video_id}")
async def get_video(video_id: str) -> dict[str, Any]:
    return db.get_video(video_id)


@app.get("/api/videos/{video_id}/playback")
async def get_playback(video_id: str) -> dict[str, str | None]:
    db.get_video(video_id)
    if playback_is_ready(video_id):
        return {
            "status": "ready",
            "manifest_url": f"/api/videos/{video_id}/playback/index.m3u8",
            "error": None,
        }
    task = PLAYBACK_TASKS.get(video_id)
    if task is not None and not task.done():
        return {"status": "preparing", "manifest_url": None, "error": None}
    if video_id in PLAYBACK_ERRORS:
        return {"status": "failed", "manifest_url": None, "error": PLAYBACK_ERRORS[video_id]}
    start_playback_preparation(video_id)
    return {"status": "preparing", "manifest_url": None, "error": None}


@app.post("/api/videos/{video_id}/playback")
async def retry_playback(video_id: str) -> dict[str, str | None]:
    db.get_video(video_id)
    PLAYBACK_ERRORS.pop(video_id, None)
    start_playback_preparation(video_id)
    return {"status": "preparing", "manifest_url": None, "error": None}


@app.get("/api/videos/{video_id}/playback/{asset_name}", response_model=None)
async def playback_asset(video_id: str, asset_name: str) -> FileResponse:
    allowed = (
        asset_name in {"index.m3u8", "init.mp4"}
        or (asset_name.startswith("segment-") and asset_name.endswith(".m4s") and asset_name[8:-4].isdigit())
    )
    if not allowed:
        raise HTTPException(status_code=404, detail="Playback asset not found")
    path = playback_directory(video_id) / asset_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Playback asset not found")
    media_type = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".mp4": "video/mp4",
        ".m4s": "video/iso.segment",
    }[path.suffix]
    cache_control = "no-cache" if asset_name == "index.m3u8" else "public, max-age=31536000, immutable"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": cache_control})


@app.get("/api/videos/{video_id}/content", response_model=None)
async def stream_video(video_id: str, request: Request) -> StreamingResponse | JSONResponse:
    path = db.video_path(video_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Video file is missing")
    size = path.stat().st_size
    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = 200
    if range_header:
        try:
            value = range_header.removeprefix("bytes=").split(",")[0]
            start_text, end_text = value.split("-", 1)
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else size - 1
            else:
                length = int(end_text)
                start = max(0, size - length)
            if start < 0 or start >= size or end < start:
                raise ValueError
            end = min(end, size - 1)
            status_code = 206
        except (ValueError, IndexError):
            return JSONResponse({"detail": "Invalid byte range"}, status_code=416, headers={"Content-Range": f"bytes */{size}"})

    chunk_size = 1024 * 1024

    async def iterator():
        with path.open("rb") as source:
            source.seek(start)
            remaining = end - start + 1
            while remaining:
                chunk = source.read(min(chunk_size, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    mime_type = db.get_video_mime_type(video_id)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Cache-Control": "no-cache",
    }
    if status_code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(iterator(), status_code=status_code, media_type=mime_type, headers=headers)


@app.post("/api/videos/{video_id}/round-export", response_model=None)
async def export_rounds(video_id: str, request: RoundExportRequest) -> TemporaryVideoResponse:
    video = db.get_video(video_id)
    source = db.video_path(video_id)
    if not source.exists():
        raise HTTPException(status_code=404, detail="Video file is missing")
    if any(clip.end_seconds > video["duration"] + 0.001 for clip in request.clips):
        raise HTTPException(status_code=400, detail="A selected round extends beyond the source video")

    export_directory = Path(tempfile.mkdtemp(prefix="vod-round-export-"))
    output = export_directory / "rounds.mp4"
    try:
        await asyncio.to_thread(build_round_export, source, output, request.clips)
    except Exception:
        shutil.rmtree(export_directory, ignore_errors=True)
        raise

    source_stem = "".join(
        character if character.isascii() and (character.isalnum() or character in "-_") else "-"
        for character in Path(video["original_name"]).stem
    )
    filename = f"{source_stem or 'video'}-game-{request.game_number}-rounds.mp4"
    return TemporaryVideoResponse(output, filename, export_directory)


@app.put("/api/videos/{video_id}/bounding-box")
async def save_bounding_box(video_id: str, box: BoundingBox) -> dict[str, Any]:
    return db.save_bounding_box(video_id, box.model_dump())


@app.post("/api/videos/{video_id}/process", status_code=202)
async def start_processing(video_id: str, request: ProcessingRequest | None = None) -> dict[str, Any]:
    global WORKERS
    job_id = uuid.uuid4().hex
    batch_size = request.batch_size if request else DEFAULT_BATCH_SIZE
    sample_interval_seconds = request.sample_interval_seconds if request else SAMPLE_INTERVAL_SECONDS
    reuse_cached_crops = request.reuse_cached_crops if request else False
    payload, created = db.create_processing_job(
        video_id, job_id, batch_size, sample_interval_seconds, reuse_cached_crops
    )
    if not created:
        return payload
    if WORKERS is None:
        WORKERS = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-processor")
    WORKERS.submit(run_job, job_id)
    return payload
