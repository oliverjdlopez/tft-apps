"""Shared download configuration, URL validation, and checkpoint helpers."""

import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .media_store import MediaStore
from .models import DownloadSource

TWITCH_HOST_RE = re.compile(r"(^|\.)twitch\.tv$", re.IGNORECASE)
YOUTUBE_HOST_RE = re.compile(r"(^|\.)youtube\.com$|(^|\.)youtu\.be$", re.IGNORECASE)


def configured_media_store() -> MediaStore | None:
    """Select the suite catalogue or an explicitly disabled local downloader."""
    return MediaStore.from_env()


# ---------------------------------------------------------------------------
# Local and shared download coordination helpers
#
# Both download paths share source validation and atomic checkpoints without
# importing the public operation that chooses between them.
# ---------------------------------------------------------------------------


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


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace a complete checkpoint atomically, cleaning up temporary files."""
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
