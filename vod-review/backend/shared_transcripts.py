"""Publish completed VOD transcripts without moving their application records."""

from __future__ import annotations

import hashlib
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
    """Snapshot one completed transcript as discoverable, immutable UTF-8 text.

    Args:
        task_id: App-owned transcription identity, independent of review lifetime.

    Returns:
        A portable reference, or None when sharing is disabled or text is unfinished.
        Repeated calls reuse the same verified snapshot when its bytes match.
    """
    task = db.get_transcription_task(task_id)
    if task["status"] != "completed" or task["transcript"] is None:
        return None
    store = ResourceStore.from_env()
    if store is None:
        return None
    text = task["transcript"]
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
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
    with publication_lock:
        for resource in store.find(source=source, kind="text", limit=1):
            if resource.sha256 == digest:
                try:
                    store.resolve(resource.reference)
                    return resource.reference
                except (FileNotFoundError, ValueError):
                    # Missing/corrupt shared files can be recovered from the
                    # authoritative local transcript without running Whisper.
                    pass
        with tempfile.TemporaryDirectory(prefix="transcript-", dir=store.root) as directory:
            file = Path(directory) / "transcript.txt"
            file.write_bytes(text.encode("utf-8"))
            resource = store.publish(
                file, kind="text", source=source, name=name,
                content_type="text/plain; charset=utf-8",
                metadata={"type": "transcript", "application": "vod-review",
                          "transcription_task_id": task_id, "video_id": task["video_id"],
                          "language": task["language"]},
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
