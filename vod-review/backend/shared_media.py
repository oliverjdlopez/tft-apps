"""Keep VOD review records separate from the shared media catalog."""

from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path
from typing import Callable

try:
    from . import db
    from .media_store import MediaStore
    from .media_store.models import MediaRequest
    from .media_store.utils import probe, source_key
except ImportError:
    import db
    from media_store import MediaStore
    from media_store.models import MediaRequest
    from media_store.utils import probe, source_key


def download_shared_video(url: str, start: float | None, end: float | None,
                          quality: str, download: Callable[[], dict]) -> dict:
    """Bind an app-owned review record to shared immutable media, without uploads."""
    store = MediaStore.from_env()
    if store is None:
        return download()
    created = []

    def produce() -> Path:
        """Retain the existing downloader's progress, checkpoint, and pause logic."""
        video = download()
        created.append(video)
        return db.video_path(video["id"])

    path = store.obtain(MediaRequest(
        url=url, kind="video", start=start or 0.0, end=end,
        profile="video:" + quality,
        height=None if quality == "best" else int(quality.removesuffix("p")),
        playable=True,
    ), produce)
    if created:
        video = created[0]
        original = db.video_path(video["id"])
        db.bind_shared_media(video["id"], path)
        original.unlink(missing_ok=True)
        return db.get_video(video["id"])

    # The media is shared, but boxes and analysis jobs belong to
    # this new review. Never merge that task state just because URLs match.
    metadata = probe(path)
    video = db.create_video(
        uuid.uuid4().hex, source_key(url).replace(":", "-") + ".mp4", path,
        mimetypes.guess_type(path.name)[0] or "video/mp4",
        metadata["duration"], metadata["width"], metadata["height"], shared_media=True,
    )
    return video


def download_shared_audio(url: str, download: Callable[[], Path]) -> Path:
    """Publish completed audio downloads or reuse any compatible cached audio stream.

    Args:
        url: Stable Twitch/YouTube source identity.
        download: Existing local audio downloader returning a completed file.

    Returns:
        Immutable shared media, or the original local file when sharing is disabled.
    """
    store = MediaStore.from_env()
    if store is None:
        return download()
    created: list[Path] = []

    def produce() -> Path:
        """Track caller-owned audio so it can be removed only after publication."""
        path = download()
        created.append(path)
        return path

    path = store.obtain(MediaRequest(url=url, kind="audio", profile="audio"), produce)
    for original in created:
        original.unlink(missing_ok=True)
    return path
