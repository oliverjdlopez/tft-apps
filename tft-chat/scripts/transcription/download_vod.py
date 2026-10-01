"""Download Twitch or YouTube media with resumable yt-dlp checkpoints."""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import parse_qs, urlparse

TWITCH_HOST_RE = re.compile(r"(^|\.)twitch\.tv$", re.IGNORECASE)
YOUTUBE_HOST_RE = re.compile(r"(^|\.)youtube\.com$|(^|\.)youtu\.be$", re.IGNORECASE)
FFMPEG_SEGFAULT_CODE = -11
AUDIO_FORMAT_SELECTOR = "bestaudio/best"
VIDEO_FORMAT_SELECTOR = "bestvideo+bestaudio/best"
DownloadMediaType = Literal["audio", "video"]
DownloadSource = Literal["twitch", "youtube"]
DEFAULT_DATA_DIR = Path("data")


@dataclass(frozen=True)
class DownloadConfig:
    """Configuration for downloading supported media."""

    url: str
    output_dir: Path = DEFAULT_DATA_DIR
    filename_template: str = "%(extractor_key)s-%(id)s.%(ext)s"
    format_selector: str = AUDIO_FORMAT_SELECTOR
    media_type: DownloadMediaType = "audio"
    merge_output_format: str | None = None
    retries: int = 10
    fragment_retries: int = 10
    concurrent_fragments: int = 4
    max_time: float | None = None
    ffmpeg_location: str | None = None
    overwrite: bool = False


@dataclass(frozen=True)
class DownloadResult:
    """The downloaded media path and associated checkpoint artifacts."""

    media_path: Path
    info_json_path: Path
    progress_path: Path
    archive_path: Path
    source: DownloadSource

    @property
    def video_path(self) -> Path:
        """Backward-compatible alias for callers that predate audio-only downloads."""

        return self.media_path


@dataclass(frozen=True)
class FfmpegLocation:
    """Resolved ffmpeg executable passed to yt-dlp."""

    path: str
    source: str


def detect_download_source(url: str) -> DownloadSource:
    """Return the supported media source for a URL."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Expected an http(s) Twitch or YouTube URL, got: {url}")
    host = parsed.netloc.split("@")[-1].split(":")[0]
    if TWITCH_HOST_RE.search(host):
        return "twitch"
    if YOUTUBE_HOST_RE.search(host):
        return "youtube"
    raise ValueError(f"Expected an http(s) Twitch or YouTube URL, got: {url}")


def validate_twitch_url(url: str) -> None:
    """Backward-compatible validation for callers that still expect Twitch only."""

    if detect_download_source(url) != "twitch":
        raise ValueError(f"Expected an http(s) twitch.tv URL, got: {url}")


def validate_media_url(url: str) -> None:
    """Reject unsupported URLs before invoking yt-dlp."""

    detect_download_source(url)


def _media_id_from_url(url: str, source: DownloadSource) -> str | None:
    parsed = urlparse(url)
    if source == "youtube":
        host = parsed.netloc.split("@")[-1].split(":")[0].lower()
        if host.endswith("youtu.be"):
            return parsed.path.strip("/").split("/", 1)[0] or None
        query_id = parse_qs(parsed.query).get("v", [None])[0]
        if query_id:
            return query_id
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
            return parts[1]
    if source == "twitch":
        match = re.search(r"/videos/(\d+)", parsed.path)
        if match:
            return match.group(1)
    return None


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            json.dump(payload, tmp_file, indent=2, sort_keys=True)
            tmp_path = Path(tmp_file.name)
        tmp_path.replace(path)
    finally:
        if tmp_path is not None and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _serializable_progress(progress: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in progress.items()
        if isinstance(value, (str, int, float, bool, type(None), Path))
    }


def _bundled_ffmpeg_path() -> str | None:
    if importlib.util.find_spec("imageio_ffmpeg") is None:
        return None

    imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


def _resolve_ffmpeg_location(explicit_location: str | None = None) -> FfmpegLocation | None:
    """Prefer a system ffmpeg over imageio's bundled binary.

    The bundled imageio-ffmpeg executable is convenient for new installs, but it
    can segfault in some WSL/Linux environments while yt-dlp is downloading HLS
    ranges. A user-specified path still wins, then PATH, then the bundled binary.
    """

    if explicit_location:
        return FfmpegLocation(path=explicit_location, source="explicit")

    if system_ffmpeg := shutil.which("ffmpeg"):
        return FfmpegLocation(path=system_ffmpeg, source="system")

    if bundled_ffmpeg := _bundled_ffmpeg_path():
        return FfmpegLocation(path=bundled_ffmpeg, source="imageio-ffmpeg")

    return None


def _ffmpeg_segfault_hint(ffmpeg_location: FfmpegLocation | None) -> str:
    selected = (
        f"Selected ffmpeg ({ffmpeg_location.source}): {ffmpeg_location.path}"
        if ffmpeg_location is not None
        else "No ffmpeg executable was configured."
    )
    return (
        "ffmpeg crashed with signal 11 while yt-dlp was downloading the VOD. "
        f"{selected} Install a system ffmpeg and ensure it appears on PATH, or "
        "rerun with --ffmpeg-location /path/to/ffmpeg to avoid a crashing bundled binary."
    )


def _download_subdir(media_type: DownloadMediaType) -> str:
    if media_type == "audio":
        return "audio"
    if media_type == "video":
        return "vods"
    raise ValueError(f"Expected media_type to be 'audio' or 'video', got: {media_type}")


def _download_archive_filename(media_type: DownloadMediaType) -> str:
    if media_type == "audio":
        return "download-audio-archive.txt"
    if media_type == "video":
        return "download-archive.txt"
    raise ValueError(f"Expected media_type to be 'audio' or 'video', got: {media_type}")


def _downloaded_media_path(
    *,
    info: dict[str, Any],
    ydl: Any,
    media_dir: Path,
    merge_output_format: str | None,
) -> Path:
    for requested_download in info.get("requested_downloads") or []:
        filepath = requested_download.get("filepath")
        if filepath:
            candidate = Path(filepath)
            if candidate.exists():
                return candidate

    prepared_path = Path(ydl.prepare_filename(info))
    if merge_output_format:
        prepared_path = prepared_path.with_suffix(f".{merge_output_format}")
    if prepared_path.exists():
        return prepared_path

    video_id = info.get("id", "")
    candidates = [
        path
        for path in media_dir.glob(f"*{video_id}*")
        if path.is_file()
        and path.suffix not in {".part", ".ytdl"}
        and not path.name.endswith(".info.json")
    ]
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime)
    return prepared_path


def _existing_media_path_from_archive_skip(
    *,
    url: str,
    source: DownloadSource,
    media_dir: Path,
) -> Path | None:
    media_id = _media_id_from_url(url, source)
    if not media_id:
        return None
    candidates = [
        path
        for path in media_dir.glob(f"*{media_id}*")
        if path.is_file()
        and path.suffix not in {".part", ".ytdl"}
        and not path.name.endswith(".info.json")
    ]
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime)
    return None


def download_vod_local(config: DownloadConfig) -> DownloadResult:
    """Download supported media from beginning to end, resuming partial progress.

    yt-dlp keeps the media fragment ``.part`` file and its own resume state in
    the checkpoint directory. This function also writes a small JSON checkpoint
    after each progress callback so an interrupted run can be inspected and then
    resumed by rerunning the same command.
    """

    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, download_range_func

    source = detect_download_source(config.url)
    if config.max_time is not None and config.max_time <= 0:
        raise ValueError(f"Expected max_time to be positive minutes, got: {config.max_time}")

    output_dir = Path(config.output_dir).expanduser().resolve()
    media_dir = output_dir / _download_subdir(config.media_type)
    checkpoint_dir = output_dir / "checkpoints"
    media_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    progress_path = checkpoint_dir / "download-progress.json"
    archive_path = checkpoint_dir / _download_archive_filename(config.media_type)

    ffmpeg_location = _resolve_ffmpeg_location(config.ffmpeg_location)

    _atomic_write_json(
        progress_path,
        {
            "status": "starting",
            "config": {**asdict(config), "output_dir": str(output_dir)},
            "source": source,
            "ffmpeg_location": asdict(ffmpeg_location) if ffmpeg_location else None,
        },
    )

    def progress_hook(progress: dict[str, Any]) -> None:
        _atomic_write_json(progress_path, _serializable_progress(progress))

    options: dict[str, Any] = {
        "format": config.format_selector,
        "outtmpl": str(media_dir / config.filename_template),
        "paths": {"home": str(media_dir), "temp": str(checkpoint_dir)},
        "continuedl": not config.overwrite,
        "nopart": False,
        "retries": config.retries,
        "fragment_retries": config.fragment_retries,
        "concurrent_fragment_downloads": config.concurrent_fragments,
        "writeinfojson": True,
        "progress_hooks": [progress_hook],
        "noplaylist": True,
    }
    if config.overwrite:
        options["overwrites"] = True
    else:
        options["download_archive"] = str(archive_path)
    if config.merge_output_format:
        options["merge_output_format"] = config.merge_output_format
    if ffmpeg_location is not None:
        options["ffmpeg_location"] = ffmpeg_location.path
    if config.max_time is not None:
        if ffmpeg_location is None:
            raise RuntimeError(
                "Partial downloads require ffmpeg. Install ffmpeg on your PATH, pass "
                "--ffmpeg-location /path/to/ffmpeg, or run `uv sync` to install imageio-ffmpeg."
            )
        options["download_ranges"] = download_range_func(None, [(0, config.max_time * 60)])

    with YoutubeDL(options) as ydl:
        try:
            info = ydl.extract_info(config.url, download=True)
        except DownloadError as exc:
            message = str(exc)
            if f"ffmpeg exited with code {FFMPEG_SEGFAULT_CODE}" in message:
                _atomic_write_json(
                    progress_path,
                    {
                        "status": "failed",
                        "error": "ffmpeg segfault",
                        "ffmpeg_location": asdict(ffmpeg_location) if ffmpeg_location else None,
                    },
                )
                raise RuntimeError(_ffmpeg_segfault_hint(ffmpeg_location)) from exc
            raise
        if info is None:
            media_path = _existing_media_path_from_archive_skip(
                url=config.url,
                source=source,
                media_dir=media_dir,
            )
            if media_path is None:
                _atomic_write_json(
                    progress_path,
                    {
                        "status": "failed",
                        "source": source,
                        "error": "download skipped by archive but no existing media file was found",
                        "archive_path": str(archive_path),
                    },
                )
                raise RuntimeError(
                    "yt-dlp skipped this URL because it is already recorded in the "
                    f"download archive, but no matching media file was found in {media_dir}. "
                    "Rerun with --overwrite, or remove the archive entry and retry."
                )
        else:
            media_path = _downloaded_media_path(
                info=info,
                ydl=ydl,
                media_dir=media_dir,
                merge_output_format=config.merge_output_format,
            )

    info_json_path = media_path.with_suffix(".info.json")
    result = DownloadResult(
        media_path=media_path,
        info_json_path=info_json_path,
        progress_path=progress_path,
        archive_path=archive_path,
        source=source,
    )
    _atomic_write_json(
        progress_path,
        {
            "status": "finished",
            "source": result.source,
            "media_path": str(result.media_path),
            "video_path": str(result.video_path),
            "info_json_path": str(result.info_json_path),
            "archive_path": str(result.archive_path),
            "ffmpeg_location": asdict(ffmpeg_location) if ffmpeg_location else None,
        },
    )
    return result


def download_vod(config: DownloadConfig) -> DownloadResult:
    """Reuse compatible suite media before invoking the resumable downloader.

    Args:
        config: Source URL, representation, range, and existing download options.

    Returns:
        A catalogue-owned immutable file, or a local result when sharing is
        explicitly disabled with an empty TFT_MEDIA_DIR.
    """
    from .shared_download import download_shared
    from .utils import configured_media_store

    store = configured_media_store()
    if store is None:
        return download_vod_local(config)
    return download_shared(config, store)
