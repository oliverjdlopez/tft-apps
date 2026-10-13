"""Shared download configuration and result contracts."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AUDIO_FORMAT_SELECTOR = "bestaudio/best"
VIDEO_FORMAT_SELECTOR = "bestvideo+bestaudio/best"
DEFAULT_DATA_DIR = Path("data")
DownloadMediaType = Literal["audio", "video"]
DownloadSource = Literal["twitch", "youtube"]


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
