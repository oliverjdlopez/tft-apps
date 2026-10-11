"""Shared local media catalog v1, vendored identically in vod-review.

Only the catalog/storage protocol is shared; neither application's database or
Python environment is imported by the other. Requires a local POSIX filesystem.
"""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .models import MediaRequest
from .resources import ResourceStore
from .utils import compatible, configured_root, derive, lock_name, probe, source_key, validate_request


class MediaStore:
    """Own immutable media files and a shared SQLite catalog across processes."""

    def __init__(self, root: Path):
        """Initialize the versioned catalog without opening an application DB."""
        if os.name != "posix":
            raise RuntimeError("Shared media currently requires a POSIX host (Linux/macOS)")
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            raise RuntimeError("Shared media requires ffmpeg and ffprobe on PATH")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "media").mkdir(exist_ok=True)
        (self.root / "locks").mkdir(exist_ok=True)
        with self.connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise RuntimeError(f"Unsupported shared media catalog version: {version}")
            connection.execute("CREATE TABLE IF NOT EXISTS media_assets (id TEXT PRIMARY KEY, source TEXT NOT NULL, metadata TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS media_source ON media_assets(source)")
            connection.execute("PRAGMA user_version=1")

    @classmethod
    def from_env(cls) -> MediaStore | None:
        """Use suite storage by default, with an explicit empty value disabling it."""
        root = configured_root()
        return None if root is None else cls(root)

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Close each short-lived catalog transaction, including on failure."""
        connection = sqlite3.connect(self.root / "catalog.sqlite3", timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def source_lock(self, key: str) -> Iterator[None]:
        """Serialize one source across both apps; process death releases the lock."""
        import fcntl

        with (self.root / "locks" / lock_name(key)).open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def obtain(self, request: MediaRequest, download: Callable[[], Path], *, refresh: bool = False) -> Path:
        """Reuse, derive, or download an asset while holding its source lock.

        Args:
            request: Required streams, quality, and source timeline coverage.
            download: Existing app downloader returning a completed local file.
            refresh: Bypass hits while leaving previously published files intact.
        """
        validate_request(request)
        key = source_key(request.url)
        with self.source_lock(key):
            with self.connection() as connection:
                rows = [json.loads(row[0]) for row in connection.execute(
                    "SELECT metadata FROM media_assets WHERE source=? ORDER BY rowid DESC", (key,)
                )]
            for row in ([] if refresh else rows):
                path = self.root / row["path"]
                if not path.is_file() or path.stat().st_size != row["size"] or not compatible(row, request):
                    continue
                exact_range = row["start"] == request.start and row["end"] == request.end
                conversion = request.kind == "video" and (
                    request.playable and not row["playable"]
                    or request.height is not None and row["height"] > request.height
                )
                if exact_range and not conversion:
                    return path
                with tempfile.TemporaryDirectory(prefix="derive-", dir=self.root) as temporary:
                    derived = Path(temporary) / ("clip.m4a" if request.kind == "audio" else "clip.mp4")
                    derive(path, derived, row, request)
                    return self.publish(key, request, derived)

            source = Path(download())
            metadata = probe(source)
            if not metadata[request.kind]:
                raise ValueError(f"Downloaded media has no {request.kind} stream")
            if request.kind == "video" and (request.playable and not metadata["playable"] or request.height is not None and metadata["height"] > request.height):
                with tempfile.TemporaryDirectory(prefix="convert-", dir=self.root) as temporary:
                    converted = Path(temporary) / "video.mp4"
                    derive(source, converted, {**metadata, "start": request.start}, request)
                    return self.publish(key, request, converted)
            return self.publish(key, request, source)

    def publish(self, key: str, request: MediaRequest, source: Path) -> Path:
        """Atomically publish a completed file before exposing it in the catalog.

        Callers hold the source lock. The original remains owned by the caller;
        an app may remove its temporary copy only after it has bound this path.
        """
        metadata = probe(source)
        if not metadata[request.kind]:
            raise ValueError(f"Media has no {request.kind} stream")
        asset_id = uuid.uuid4().hex
        destination = self.root / "media" / (asset_id + source.suffix)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        try:
            shutil.copyfile(source, temporary)
            temporary.replace(destination)
            # A bounded download must never be advertised as covering more than
            # its actual duration. Unbounded requests retain their EOF marker.
            end = None if request.end is None else min(request.end, request.start + metadata["duration"])
            row = {**metadata, "start": request.start, "end": end, "profile": request.profile,
                   "path": str(destination.relative_to(self.root)), "size": destination.stat().st_size}
            # Index completed URL downloads for discovery by either backend.
            # ResourceStore links catalogue-owned bytes; no second media copy
            # is made, and each refresh still receives an immutable reference.
            ResourceStore(self.root).publish(
                destination, kind="video" if metadata["video"] else "audio", source=key,
                name=key.replace(":", "-") + source.suffix,
                content_type=mimetypes.guess_type(destination.name)[0] or "application/octet-stream",
                metadata={name: value for name, value in row.items() if name != "path"},
            )
            with self.connection() as connection:
                connection.execute("INSERT INTO media_assets VALUES(?,?,?)", (asset_id, key, json.dumps(row)))
            return destination
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
