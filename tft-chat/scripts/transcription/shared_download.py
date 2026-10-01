"""Adapt the transcription downloader to the independent shared media catalog."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .media_store import MediaStore
from .media_store.models import MediaRequest

if TYPE_CHECKING:
    from .download_vod import DownloadConfig, DownloadResult


def download_shared(config: DownloadConfig, store: MediaStore) -> DownloadResult:
    """Use shared assets and isolate legacy archives by source, range, and format."""
    from .download_vod import (
        AUDIO_FORMAT_SELECTOR, VIDEO_FORMAT_SELECTOR, DownloadResult,
        _atomic_write_json, detect_download_source, download_vod_local,
    )

    profile = {AUDIO_FORMAT_SELECTOR: "audio", VIDEO_FORMAT_SELECTOR: "video:best"}.get(
        config.format_selector, "selector:" + config.format_selector
    )
    request = MediaRequest(
        url=config.url, kind=config.media_type, profile=profile,
        end=None if config.max_time is None else config.max_time * 60,
    )
    downloaded = []

    def produce() -> Path:
        """Download into a resumable work directory unique to this representation."""
        from .media_store.utils import source_key

        identity = json.dumps([source_key(config.url), config.media_type, config.format_selector,
                               config.merge_output_format, config.max_time])
        work = store.root / "work" / hashlib.sha256(identity.encode()).hexdigest()
        # The catalog has already checked for completed media. A stale archive
        # must not suppress recovery when its former media file has disappeared.
        archive = work / "checkpoints" / ("download-audio-archive.txt" if config.media_type == "audio" else "download-archive.txt")
        archive.unlink(missing_ok=True)
        result = download_vod_local(replace(config, output_dir=work))
        downloaded.append(result)
        return result.media_path

    path = store.obtain(request, produce, refresh=config.overwrite)
    info_path = path.with_suffix(".info.json")
    if not info_path.exists():
        info = {"source_url": config.url, "shared_media": True}
        if downloaded and downloaded[0].info_json_path.is_file():
            info = json.loads(downloaded[0].info_json_path.read_text())
        _atomic_write_json(info_path, info)
    progress_path = store.root / "work" / ("request-" + uuid.uuid4().hex + ".json")
    _atomic_write_json(progress_path, {"status": "finished", "media_path": str(path), "shared_media": True})
    if downloaded:
        from .media_store.utils import source_key

        # Another process may have begun a refresh in this resumable work
        # directory since obtain returned. Never unlink its active output.
        with store.source_lock(source_key(config.url)):
            downloaded[0].media_path.unlink(missing_ok=True)
    return DownloadResult(
        media_path=path, info_json_path=info_path, progress_path=progress_path,
        archive_path=store.root / "catalog.sqlite3", source=detect_download_source(config.url),
    )
