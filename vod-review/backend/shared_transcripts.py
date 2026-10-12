"""Publish completed VOD transcripts without moving their application records."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
import tempfile
import threading

try:
    from . import db
    from .media_store.resources import ResourceStore
except ImportError:  # Support the documented backend-directory launch.
    import db
    from media_store.resources import ResourceStore

logger = logging.getLogger(__name__)
# Startup recovery and transcription workers share one owned VOD runtime.
# Serialize their lookup/publication pair so retries cannot add duplicate copies.
publication_lock = threading.Lock()


def publish_transcript(task_id: str) -> str | None:
    """Snapshot completed text and its available timing as linked shared resources.

    Args:
        task_id: App-owned transcription identity, independent of review lifetime.

    Returns:
        A portable reference, or None when sharing is disabled or text is unfinished.
        Repeated calls reuse the same verified snapshot when its bytes match.
    """
    task = db.get_transcription_task(task_id, include_segments=True)
    if task["status"] != "completed" or task["transcript"] is None:
        return None
    store = ResourceStore.from_env()
    if store is None:
        return None
    source = "vod-review:transcription:" + task_id
    name = "transcript-" + task_id + ".txt"
    if task["video_id"]:
        connection = db.get_db()
        try:
            video = connection.execute("SELECT original_name FROM videos WHERE id=?", (task["video_id"],)).fetchone()
        finally:
            connection.close()
        if video is not None:
            name = Path(video["original_name"]).stem + ".transcript.txt"
    metadata = {"type": "transcript", "application": "vod-review",
                "transcription_task_id": task_id, "video_id": task["video_id"],
                "language": task["language"]}
    with publication_lock:
        reference = publish_snapshot(
            store, task["transcript"].encode("utf-8"), kind="text", source=source,
            name=name, content_type="text/plain; charset=utf-8", metadata=metadata,
        )
        # Legacy results have no timing to recover. Empty segments, however,
        # are a valid new recognition result (e.g. media containing silence).
        if task["segments"] is not None:
            payload = {
                "schema_version": 1, "transcription_task_id": task_id,
                "video_id": task["video_id"], "language": task["language"],
                "text_reference": reference, "transcript": task["transcript"],
                "time_unit": "seconds", "time_origin": "media_start",
                "segments": task["segments"],
            }
            publish_snapshot(
                store, json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8"),
                kind="data", source=source, name=Path(name).with_suffix(".json").name,
                content_type="application/json",
                metadata={**metadata, "type": "timestamped_transcript", "schema_version": 1,
                          "text_reference": reference},
            )
        return reference


def publish_snapshot(store: ResourceStore, content: bytes, *, kind: str, source: str,
                     name: str, content_type: str, metadata: dict) -> str:
    """Reuse verified matching bytes or publish a recoverable immutable snapshot.

    Args:
        store: Shared catalogue receiving the snapshot.
        content: Exact bytes from the authoritative local result.
        kind: Catalogue resource kind.
        source: Stable transcription source identity.
        name: Display filename.
        content_type: MIME type of the snapshot.
        metadata: Provenance and related resource references.

    Returns:
        The verified existing or newly published portable reference.
    """
    digest = hashlib.sha256(content).hexdigest()
    for resource in store.find(source=source, kind=kind, limit=1):
        if resource.sha256 == digest:
            try:
                store.resolve(resource.reference)
                return resource.reference
            except (FileNotFoundError, ValueError):
                # Restore missing/corrupt files without running Whisper again.
                pass
    with tempfile.TemporaryDirectory(prefix="transcript-", dir=store.root) as directory:
        file = Path(directory) / name
        file.write_bytes(content)
        resource = store.publish(
            file, kind=kind, source=source, name=name,
            content_type=content_type, metadata=metadata,
        )
    return resource.reference


def publish_completed_transcripts(task_id: str | None = None) -> int:
    """Publish new or existing results while preserving successful local tasks.

    Args:
        task_id: One just-completed task, or None to recover all existing results.

    Returns:
        Number of completed tasks with shared snapshots. Publication failures are
        logged and retried on the next backend startup; inference is never rerun.
    """
    if task_id is None:
        connection = db.get_db()
        try:
            tasks = [row["id"] for row in connection.execute(
                "SELECT id FROM transcription_tasks WHERE status='completed' AND transcript IS NOT NULL"
            )]
        finally:
            connection.close()
    else:
        tasks = [task_id]
    count = 0
    for identity in tasks:
        try:
            if publish_transcript(identity) is not None:
                count += 1
        except Exception:
            # Catalogue availability must not turn completed recognition into a
            # failed task or prevent the VOD application from starting.
            logger.warning("Could not share completed transcript %s; retry on backend startup", identity, exc_info=True)
    return count
