from __future__ import annotations

import json
import os
import re
from urllib.parse import parse_qs, urlparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

try:
    from .constants import DEFAULT_BATCH_SIZE, SAMPLE_INTERVAL_SECONDS
except ImportError:  # Running from the backend directory.
    from constants import DEFAULT_BATCH_SIZE, SAMPLE_INTERVAL_SECONDS


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VOD_DATA_DIR", ROOT / "data"))
VIDEO_DIR = DATA_DIR / "videos"
DOWNLOAD_DIR = DATA_DIR / "downloads"
DB_PATH = DATA_DIR / "vod.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    connection = get_db()
    connection.executescript(
        f"""
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY, original_name TEXT NOT NULL, path TEXT,
            mime_type TEXT NOT NULL, duration REAL NOT NULL, width INTEGER NOT NULL,
            height INTEGER NOT NULL, created_at TEXT NOT NULL, box_x REAL,
            box_y REAL, box_width REAL, box_height REAL, box_frame_time REAL,
            current_job_id TEXT
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, video_id TEXT NOT NULL, status TEXT NOT NULL,
            progress INTEGER NOT NULL DEFAULT 0, total_samples INTEGER NOT NULL DEFAULT 0,
            collected_samples INTEGER NOT NULL DEFAULT 0,
            batch_size INTEGER NOT NULL DEFAULT {DEFAULT_BATCH_SIZE},
            sample_interval_seconds REAL NOT NULL DEFAULT {SAMPLE_INTERVAL_SECONDS},
            phase TEXT NOT NULL DEFAULT 'queued', max_timing_error_ms REAL, device TEXT,
            reuse_cached_crops INTEGER NOT NULL DEFAULT 0, source_job_id TEXT,
            error TEXT, box_x REAL NOT NULL, box_y REAL NOT NULL, box_width REAL NOT NULL,
            box_height REAL NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, video_id TEXT NOT NULL,
            timestamp_seconds REAL NOT NULL, scheduled_timestamp_seconds REAL,
            red REAL NOT NULL DEFAULT 0, green REAL NOT NULL DEFAULT 0, blue REAL NOT NULL DEFAULT 0,
            class_label TEXT, confidence REAL,
            FOREIGN KEY(job_id) REFERENCES jobs(id), FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        CREATE TABLE IF NOT EXISTS download_tasks (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            video_id TEXT, error TEXT, url TEXT, start_seconds REAL, end_seconds REAL,
            checkpoint_interval_seconds REAL, quality TEXT NOT NULL DEFAULT '720p',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS transcription_tasks (
            id TEXT PRIMARY KEY, video_id TEXT, media_path TEXT,
            status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            transcript TEXT, language TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_results_job_time ON results(job_id, timestamp_seconds);
        """
    )
    _migrate_nullable_video_path(connection)
    transcription_columns = {row["name"] for row in connection.execute("PRAGMA table_info(transcription_tasks)")}
    if "segments_json" not in transcription_columns:
        # NULL distinguishes older text-only results from timed silence ([]).
        connection.execute("ALTER TABLE transcription_tasks ADD COLUMN segments_json TEXT")
    video_columns = {row["name"] for row in connection.execute("PRAGMA table_info(videos)")}
    if "shared_media" not in video_columns:
        connection.execute("ALTER TABLE videos ADD COLUMN shared_media INTEGER NOT NULL DEFAULT 0")
    for column, declaration in (("mode", "TEXT NOT NULL DEFAULT 'offline'"), ("source_url", "TEXT"), ("source_id", "TEXT"), ("source_start_seconds", "REAL NOT NULL DEFAULT 0"), ("source_end_seconds", "REAL"), ("source_quality", "TEXT NOT NULL DEFAULT '720p'")):
        if column not in video_columns:
            connection.execute(f"ALTER TABLE videos ADD COLUMN {column} {declaration}")
    job_columns = {row["name"] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()}
    if "collected_samples" not in job_columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN collected_samples INTEGER NOT NULL DEFAULT 0")
    if "batch_size" not in job_columns:
        connection.execute(
            f"ALTER TABLE jobs ADD COLUMN batch_size INTEGER NOT NULL DEFAULT {DEFAULT_BATCH_SIZE}"
        )
    if "sample_interval_seconds" not in job_columns:
        connection.execute(
            f"ALTER TABLE jobs ADD COLUMN sample_interval_seconds REAL NOT NULL DEFAULT {SAMPLE_INTERVAL_SECONDS}"
        )
    if "phase" not in job_columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN phase TEXT NOT NULL DEFAULT 'queued'")
    if "max_timing_error_ms" not in job_columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN max_timing_error_ms REAL")
    if "reuse_cached_crops" not in job_columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN reuse_cached_crops INTEGER NOT NULL DEFAULT 0")
    if "source_job_id" not in job_columns:
        connection.execute("ALTER TABLE jobs ADD COLUMN source_job_id TEXT")
    for column, declaration in (("strategy", "TEXT NOT NULL DEFAULT 'offline'"), ("refinement_interval_seconds", "REAL NOT NULL DEFAULT 1")):
        if column not in job_columns:
            connection.execute(f"ALTER TABLE jobs ADD COLUMN {column} {declaration}")
    result_columns = {row["name"] for row in connection.execute("PRAGMA table_info(results)").fetchall()}
    if "scheduled_timestamp_seconds" not in result_columns:
        connection.execute("ALTER TABLE results ADD COLUMN scheduled_timestamp_seconds REAL")
    if "class_label" not in result_columns:
        connection.execute("ALTER TABLE results ADD COLUMN class_label TEXT")
    if "confidence" not in result_columns:
        connection.execute("ALTER TABLE results ADD COLUMN confidence REAL")
    download_columns = {row["name"] for row in connection.execute("PRAGMA table_info(download_tasks)").fetchall()}
    for column, declaration in (
        ("target_video_id", "TEXT"),
        ("url", "TEXT"),
        ("start_seconds", "REAL"),
        ("end_seconds", "REAL"),
        ("checkpoint_interval_seconds", "REAL"),
        ("quality", "TEXT NOT NULL DEFAULT '720p'"),
        ("target_fps", "REAL"),
        ("media_type", "TEXT NOT NULL DEFAULT 'video'"),
        ("transcribe", "INTEGER NOT NULL DEFAULT 0"),
        ("media_path", "TEXT"),
        ("transcription_task_id", "TEXT"),
    ):
        if column not in download_columns:
            connection.execute(f"ALTER TABLE download_tasks ADD COLUMN {column} {declaration}")
    _recover_download_sources(connection)
    connection.execute(
        "UPDATE results SET scheduled_timestamp_seconds=timestamp_seconds WHERE scheduled_timestamp_seconds IS NULL"
    )
    connection.execute(
        "UPDATE jobs SET status='failed', phase='failed', error='Interrupted by server restart; retry this analysis.', updated_at=datetime('now') WHERE status IN ('queued', 'running')"
    )
    connection.execute(
        "UPDATE download_tasks SET status='paused', error=NULL, updated_at=? "
        "WHERE status IN ('queued', 'running', 'pausing') AND checkpoint_interval_seconds IS NOT NULL",
        (utc_now(),),
    )
    connection.execute(
        "UPDATE download_tasks SET status='failed', error='Interrupted by server restart; retry this download.', updated_at=? "
        "WHERE status IN ('queued', 'running', 'pausing')",
        (utc_now(),),
    )
    connection.execute(
        "UPDATE transcription_tasks SET status='failed', error='Interrupted by server restart; retry this transcription.', updated_at=? "
        "WHERE status IN ('queued', 'running')",
        (utc_now(),),
    )
    connection.commit()
    connection.execute("PRAGMA optimize")
    connection.close()


def _migrate_nullable_video_path(connection: sqlite3.Connection) -> None:
    """Allow remote records while preserving the stored schema and referencing tables."""
    columns = connection.execute("PRAGMA table_info(videos)").fetchall()
    if not any(row["name"] == "path" and row["notnull"] for row in columns):
        return
    schema = connection.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='videos'").fetchone()["sql"]
    objects = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='videos' AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    # Renaming the old table would rewrite external foreign key references.
    schema = re.sub(r'CREATE TABLE\s+(?:"videos"|videos)', 'CREATE TABLE videos_nullable_migration', schema, count=1, flags=re.I)
    schema = re.sub(r'(\bpath\s+TEXT)\s+NOT\s+NULL', r'\1', schema, count=1, flags=re.I)
    names = ', '.join('"' + row["name"].replace('"', '""') + '"' for row in columns)
    legacy_alter = connection.execute("PRAGMA legacy_alter_table").fetchone()[0]
    # Existing views briefly refer to a missing table during replacement. Legacy
    # rename avoids validating that transient state or rewriting their references.
    connection.execute("PRAGMA legacy_alter_table=ON")
    try:
        with connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(schema)
            connection.execute(f"INSERT INTO videos_nullable_migration ({names}) SELECT {names} FROM videos")
            connection.execute("DROP TABLE videos")
            connection.execute("ALTER TABLE videos_nullable_migration RENAME TO videos")
            for row in objects:
                connection.execute(row["sql"])
    finally:
        connection.execute(f"PRAGMA legacy_alter_table={int(legacy_alter)}")


def _youtube_source_id(url: str) -> str | None:
    """Extract YouTube identity from established download URLs without network access."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in {"youtu.be", "www.youtu.be"}:
        candidate = parsed.path.strip('/').split('/')[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        candidate = parse_qs(parsed.query).get("v", [""])[0]
        if not candidate and parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            candidate = parsed.path.split('/')[2]
    else:
        return None
    return candidate if re.fullmatch(r'[A-Za-z0-9_-]{11}', candidate) else None


def _online_source(url: str) -> tuple[str, str] | None:
    """Recover stable playback identity without resolving remote transports."""
    youtube_id = _youtube_source_id(url)
    if youtube_id:
        return youtube_id, f"https://www.youtube.com/watch?v={youtube_id}"
    try:
        from .online import canonical_source
    except ImportError:
        from online import canonical_source
    try:
        return canonical_source(url)
    except ValueError:
        return None


def _recover_download_sources(connection: sqlite3.Connection) -> None:
    """Recover metadata only from completed download tasks linked to existing reviews."""
    rows = connection.execute("SELECT d.*, v.duration AS local_duration FROM download_tasks d JOIN videos v ON v.id=d.video_id WHERE d.status='completed' AND d.url IS NOT NULL AND v.source_id IS NULL ORDER BY d.updated_at").fetchall()
    for row in rows:
        source = _online_source(row["url"])
        if source:
            source_id, source_url = source
            start = row["start_seconds"] or 0
            end = row["end_seconds"] if row["end_seconds"] is not None else start + row["local_duration"]
            connection.execute("UPDATE videos SET source_id=?, source_url=?, source_start_seconds=?, source_end_seconds=?, source_quality=? WHERE id=? AND source_id IS NULL", (source_id, source_url, start, end, row["quality"], row["video_id"]))


def physical_video_path(video_id: str) -> Path | None:
    """Return the stored path independently of selected playback mode."""
    connection = get_db()
    try:
        row = connection.execute("SELECT path FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Video not found")
        return Path(row["path"]) if row["path"] else None
    finally:
        connection.close()


def video_path(video_id: str) -> Path:
    """Require Offline mode and an existing local copy for local media operations."""
    video = get_video(video_id)
    path = physical_video_path(video_id)
    if video["mode"] != "offline" or path is None or not path.is_file():
        raise HTTPException(status_code=409, detail="Switch to Offline mode and download a local copy first")
    return path


def serialize_job(connection: sqlite3.Connection, job: sqlite3.Row | None) -> dict[str, Any] | None:
    if job is None:
        return None
    results = connection.execute(
        "SELECT timestamp_seconds, scheduled_timestamp_seconds, class_label, confidence "
        "FROM results WHERE job_id=? AND class_label IS NOT NULL ORDER BY scheduled_timestamp_seconds",
        (job["id"],),
    ).fetchall()
    fields = (
        "id",
        "status",
        "progress",
        "total_samples",
        "collected_samples",
        "batch_size",
        "sample_interval_seconds",
        "strategy",
        "refinement_interval_seconds",
        "source_job_id",
        "phase",
        "max_timing_error_ms",
        "device",
        "error",
        "created_at",
        "updated_at",
    )
    return {
        **{key: job[key] for key in fields},
        "reuse_cached_crops": bool(job["reuse_cached_crops"]),
        "results": [
            {
                "timestamp_seconds": row["timestamp_seconds"],
                "scheduled_timestamp_seconds": row["scheduled_timestamp_seconds"],
                "timing_error_ms": round(
                    (row["timestamp_seconds"] - row["scheduled_timestamp_seconds"]) * 1000,
                    3,
                ),
                "class_label": row["class_label"],
                "confidence": row["confidence"],
            }
            for row in results
        ],
    }


def serialize_video(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    box = None
    if row["box_x"] is not None:
        box = {
            "x": row["box_x"],
            "y": row["box_y"],
            "width": row["box_width"],
            "height": row["box_height"],
            "frame_time": row["box_frame_time"],
        }
    current = None
    if row["current_job_id"]:
        current = serialize_job(
            connection,
            connection.execute("SELECT * FROM jobs WHERE id=?", (row["current_job_id"],)).fetchone(),
        )
    active = connection.execute(
        "SELECT * FROM jobs WHERE video_id=? AND status IN ('queued','running') "
        "ORDER BY created_at DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    latest = connection.execute(
        "SELECT * FROM jobs WHERE video_id=? ORDER BY created_at DESC LIMIT 1",
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "mode": row["mode"],
        "source_url": row["source_url"],
        "source_id": row["source_id"],
        "source_start_seconds": row["source_start_seconds"],
        "source_end_seconds": row["source_end_seconds"],
        "source_quality": row["source_quality"],
        "local_available": bool(row["path"] and Path(row["path"]).is_file()),
        "mime_type": row["mime_type"],
        "duration": row["duration"],
        "width": row["width"],
        "height": row["height"],
        "created_at": row["created_at"],
        "box": box,
        "current_job": current,
        "active_job": serialize_job(connection, active),
        "latest_job": serialize_job(connection, latest),
    }


def create_video(
    video_id: str,
    original_name: str,
    path: Path,
    mime_type: str,
    duration: float,
    width: int,
    height: int,
    shared_media: bool = False,
) -> dict[str, Any]:
    connection = get_db()
    connection.execute(
        "INSERT INTO videos(id, original_name, path, mime_type, duration, width, height, created_at, shared_media) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (video_id, original_name, str(path), mime_type, duration, width, height, utc_now(), int(shared_media)),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    payload = serialize_video(connection, row)
    connection.close()
    return payload


def list_videos() -> list[dict[str, Any]]:
    connection = get_db()
    rows = connection.execute("SELECT * FROM videos ORDER BY created_at DESC").fetchall()
    payload = [serialize_video(connection, row) for row in rows]
    connection.close()
    return payload


def get_video(video_id: str) -> dict[str, Any]:
    connection = get_db()
    row = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if row is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Video not found")
    payload = serialize_video(connection, row)
    connection.close()
    return payload


def create_download_task(
    task_id: str,
    *,
    url: str | None = None,
    start_seconds: float | None = None,
    end_seconds: float | None = None,
    checkpoint_interval_seconds: float | None = None,
    quality: str = "720p",
    target_fps: float | None = None,
    media_type: str = "video",
    transcribe: bool = False,
    target_video_id: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    connection = get_db()
    connection.execute(
        "INSERT INTO download_tasks(id, status, progress, url, start_seconds, end_seconds, "
        "checkpoint_interval_seconds, quality, target_fps, media_type, transcribe, created_at, updated_at, target_video_id) "
        "VALUES(?, 'queued', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, url, start_seconds, end_seconds, checkpoint_interval_seconds, quality, target_fps, media_type, int(transcribe), now, now, target_video_id),
    )
    connection.commit()
    connection.close()
    return {"task_id": task_id, "status": "queued", "progress": 0.0, "video": None, "error": None}


def get_download_request(task_id: str) -> dict[str, Any]:
    connection = get_db()
    row = connection.execute(
        "SELECT url, start_seconds, end_seconds, checkpoint_interval_seconds, quality, target_fps, media_type, transcribe, target_video_id FROM download_tasks WHERE id=?",
        (task_id,),
    ).fetchone()
    connection.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Download task not found")
    if not row["url"]:
        raise HTTPException(status_code=409, detail="This older download cannot be resumed")
    return dict(row)


def update_download_task(
    task_id: str,
    *,
    status: str | None = None,
    progress: float | None = None,
    video_id: str | None = None,
    error: str | None = None,
    media_path: str | None = None,
    transcription_task_id: str | None = None,
) -> None:
    connection = get_db()
    current = connection.execute("SELECT progress FROM download_tasks WHERE id=?", (task_id,)).fetchone()
    if current is None:
        connection.close()
        return
    assignments = ["updated_at=?"]
    values: list[Any] = [utc_now()]
    if status is not None:
        assignments.append("status=?")
        values.append(status)
    if progress is not None:
        assignments.append("progress=?")
        values.append(max(float(current["progress"]), min(100.0, max(0.0, progress))))
    if video_id is not None:
        assignments.append("video_id=?")
        values.append(video_id)
    if error is not None:
        assignments.append("error=?")
        values.append(error)
    if media_path is not None:
        assignments.append("media_path=?")
        values.append(media_path)
    if transcription_task_id is not None:
        assignments.append("transcription_task_id=?")
        values.append(transcription_task_id)
    values.append(task_id)
    connection.execute(f"UPDATE download_tasks SET {', '.join(assignments)} WHERE id=?", values)
    connection.commit()
    connection.close()


def get_download_task(task_id: str) -> dict[str, Any]:
    connection = get_db()
    row = connection.execute("SELECT * FROM download_tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Download task not found")
    video = None
    if row["video_id"]:
        video_row = connection.execute("SELECT * FROM videos WHERE id=?", (row["video_id"],)).fetchone()
        if video_row is not None:
            video = serialize_video(connection, video_row)
    payload = {
        "task_id": row["id"],
        "status": row["status"],
        "progress": float(row["progress"]),
        "video": video,
        "error": row["error"],
        "media_type": row["media_type"],
        "target_video_id": row["target_video_id"],
        "transcription_task_id": row["transcription_task_id"],
        "transcription": get_transcription_task(row["transcription_task_id"], connection) if row["transcription_task_id"] else None,
    }
    connection.close()
    return payload


def create_transcription_task(task_id: str, media_path: str, video_id: str | None = None) -> dict[str, Any]:
    now = utc_now()
    connection = get_db()
    connection.execute(
        "INSERT INTO transcription_tasks(id, video_id, media_path, status, created_at, updated_at) VALUES(?, ?, ?, 'queued', ?, ?)",
        (task_id, video_id, media_path, now, now),
    )
    connection.commit()
    connection.close()
    return get_transcription_task(task_id)


def update_transcription_task(task_id: str, *, status: str | None = None, transcript: str | None = None, language: str | None = None, error: str | None = None, segments: list[dict[str, Any]] | None = None) -> None:
    """Persist recognition text and optional timing together before sharing.

    Args:
        task_id: Local transcription identity.
        status: New task state, when supplied.
        transcript: Recognized plain text, when supplied.
        language: Detected language, when available.
        error: Failure detail, when supplied.
        segments: Timed speech segments; None preserves legacy text-only data.
    """
    assignments = ["updated_at=?"]
    values: list[Any] = [utc_now()]
    for column, value in (("status", status), ("transcript", transcript), ("language", language), ("error", error)):
        if value is not None:
            assignments.append(f"{column}=?")
            values.append(value)
    if segments is not None:
        assignments.append("segments_json=?")
        values.append(json.dumps(segments, ensure_ascii=False, allow_nan=False))
    values.append(task_id)
    connection = get_db()
    connection.execute(f"UPDATE transcription_tasks SET {', '.join(assignments)} WHERE id=?", values)
    connection.commit()
    connection.close()


def get_transcription_task(task_id: str, connection: sqlite3.Connection | None = None, *, include_segments: bool = False) -> dict[str, Any]:
    """Read a task, keeping timing out of the existing UI/API payload by default.

    Args:
        task_id: Local transcription identity.
        connection: Existing connection, or None to open one for this read.
        include_segments: Load persisted timing for shared publication.

    Returns:
        The task payload, optionally including segments (None for legacy tasks).
    """
    owns_connection = connection is None
    connection = connection or get_db()
    row = connection.execute("SELECT * FROM transcription_tasks WHERE id=?", (task_id,)).fetchone()
    if owns_connection:
        connection.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Transcription task not found")
    task = {"task_id": row["id"], "video_id": row["video_id"], "status": row["status"], "transcript": row["transcript"], "language": row["language"], "error": row["error"]}
    if include_segments:
        task["segments"] = json.loads(row["segments_json"]) if row["segments_json"] is not None else None
    return task


def find_video_transcription(video_id: str, *, reusable_only: bool = False) -> dict[str, Any] | None:
    """Read a video's latest task, or prefer a successful/active reusable task.

    Args:
        video_id: Library video whose audio was recognized.
        reusable_only: Ignore failed tasks and prefer completed recognition to new work.

    Returns:
        A persisted transcription payload, or None when no matching task exists.
    """
    connection = get_db()
    try:
        conditions = "AND status IN ('completed','queued','running')" if reusable_only else ""
        order = "(status='completed') DESC," if reusable_only else ""
        row = connection.execute(
            f"SELECT id FROM transcription_tasks WHERE video_id=? {conditions} ORDER BY {order} created_at DESC,rowid DESC LIMIT 1",
            (video_id,),
        ).fetchone()
        return get_transcription_task(row["id"], connection) if row else None
    finally:
        connection.close()


def get_resumable_download_task() -> dict[str, Any] | None:
    connection = get_db()
    row = connection.execute(
        "SELECT id FROM download_tasks WHERE status IN ('queued', 'running', 'pausing', 'paused') "
        "AND (checkpoint_interval_seconds IS NOT NULL OR target_video_id IS NOT NULL) "
        "ORDER BY updated_at DESC LIMIT 1"
    ).fetchone()
    connection.close()
    return get_download_task(row["id"]) if row is not None else None


def dismiss_download_task(task_id: str) -> None:
    connection = get_db()
    row = connection.execute("SELECT status FROM download_tasks WHERE id=?", (task_id,)).fetchone()
    if row is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Download task not found")
    if row["status"] != "paused":
        connection.close()
        raise HTTPException(status_code=409, detail="Only a paused download can be dismissed")
    connection.execute(
        "UPDATE download_tasks SET status='dismissed', updated_at=? WHERE id=?",
        (utc_now(), task_id),
    )
    connection.commit()
    connection.close()


def delete_video(video_id: str) -> Path | None:
    connection = get_db()
    row = connection.execute("SELECT path FROM videos WHERE id=?", (video_id,)).fetchone()
    if row is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Video not found")
    # Retired annotation tables and authored datasets are intentionally preserved.
    job_rows = connection.execute("SELECT id FROM jobs WHERE video_id=?", (video_id,)).fetchall()
    job_ids = [job["id"] for job in job_rows]
    if job_ids:
        placeholders = ",".join("?" for _ in job_ids)
        connection.execute(f"DELETE FROM results WHERE job_id IN ({placeholders})", job_ids)
        connection.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", job_ids)
    connection.execute("DELETE FROM videos WHERE id=?", (video_id,))
    connection.commit()
    connection.close()
    return Path(row["path"]) if row["path"] else None


def get_video_mime_type(video_id: str) -> str:
    connection = get_db()
    row = connection.execute("SELECT mime_type FROM videos WHERE id=?", (video_id,)).fetchone()
    connection.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return str(row["mime_type"])


def save_bounding_box(video_id: str, box: dict[str, float]) -> dict[str, Any]:
    connection = get_db()
    exists = connection.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone()
    if exists is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Video not found")
    connection.execute(
        "UPDATE videos SET box_x=?, box_y=?, box_width=?, box_height=?, box_frame_time=? WHERE id=?",
        (box["x"], box["y"], box["width"], box["height"], box["frame_time"], video_id),
    )
    connection.commit()
    row = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    payload = serialize_video(connection, row)
    connection.close()
    return payload


def create_processing_job(
    video_id: str,
    job_id: str,
    batch_size: int,
    sample_interval_seconds: float,
    reuse_cached_crops: bool = False,
    strategy: str | None = None,
    refinement_interval_seconds: float = 1.0,
) -> tuple[dict[str, Any], bool]:
    connection = get_db()
    video = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
    if video is None:
        connection.close()
        raise HTTPException(status_code=404, detail="Video not found")
    if video["box_x"] is None:
        connection.close()
        raise HTTPException(status_code=400, detail="Save a bounding box before processing")
    active = connection.execute(
        "SELECT * FROM jobs WHERE video_id=? AND status IN ('queued','running') "
        "ORDER BY created_at DESC LIMIT 1",
        (video_id,),
    ).fetchone()
    if active is not None:
        payload = serialize_job(connection, active)
        connection.close()
        return payload, False

    strategy = strategy or video["mode"]
    if strategy not in {"online", "offline"}:
        connection.close()
        raise HTTPException(status_code=400, detail="Invalid analysis strategy")
    source_job_id = None
    if reuse_cached_crops:
        source = connection.execute(
            "SELECT * FROM jobs WHERE video_id=? AND status='completed' "
            "ORDER BY created_at DESC LIMIT 1",
            (video_id,),
        ).fetchone()
        if source is None:
            connection.close()
            raise HTTPException(status_code=409, detail="Decode the video before rerunning OCR")
        if source["strategy"] != strategy or source["sample_interval_seconds"] != sample_interval_seconds:
            connection.close()
            raise HTTPException(status_code=409, detail="The analysis interval changed; re-decode the video before rerunning OCR")
        source_job_id = source["source_job_id"] or source["id"]
        source_box = (source["box_x"], source["box_y"], source["box_width"], source["box_height"])
        current_box = (video["box_x"], video["box_y"], video["box_width"], video["box_height"])
        if source_box != current_box:
            connection.close()
            raise HTTPException(
                status_code=409,
                detail="The analysis box changed; re-decode the video before rerunning OCR",
            )

    now = utc_now()
    connection.execute(
        "INSERT INTO jobs(id, video_id, status, phase, progress, total_samples, collected_samples, "
        "batch_size, sample_interval_seconds, reuse_cached_crops, source_job_id, "
        "box_x, box_y, box_width, box_height, created_at, updated_at, strategy, refinement_interval_seconds) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            job_id,
            video_id,
            "queued",
            "queued",
            0,
            0,
            0,
            batch_size,
            sample_interval_seconds,
            int(reuse_cached_crops),
            source_job_id,
            video["box_x"],
            video["box_y"],
            video["box_width"],
            video["box_height"],
            now,
            now,
            strategy,
            refinement_interval_seconds,
        ),
    )
    connection.commit()
    job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    payload = serialize_job(connection, job)
    connection.close()
    return payload, True


def begin_job(job_id: str) -> tuple[sqlite3.Row, sqlite3.Row] | None:
    connection = get_db()
    job = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    video = None
    if job is not None:
        video = connection.execute("SELECT * FROM videos WHERE id=?", (job["video_id"],)).fetchone()
    if job is None or video is None:
        connection.close()
        return None
    connection.execute(
        "UPDATE jobs SET status='running', phase='collecting', progress=0, "
        "collected_samples=0, updated_at=? WHERE id=?",
        (utc_now(), job_id),
    )
    connection.commit()
    connection.close()
    return job, video


def set_job_total(job_id: str, total: int) -> None:
    connection = get_db()
    connection.execute(
        "UPDATE jobs SET total_samples=?, updated_at=? WHERE id=?",
        (total, utc_now(), job_id),
    )
    connection.commit()
    connection.close()


def update_frame_preparation(job_id: str, processed: int, total: int) -> None:
    connection = get_db()
    connection.execute(
        "UPDATE jobs SET phase='preparing', collected_samples=?, total_samples=?, updated_at=? WHERE id=?",
        (processed, total, utc_now(), job_id),
    )
    connection.commit()
    connection.close()


def update_collection_progress(job_id: str, collected: int, total: int) -> None:
    connection = get_db()
    connection.execute(
        "UPDATE jobs SET phase='collecting', collected_samples=?, total_samples=?, updated_at=? "
        "WHERE id=?",
        (collected, total, utc_now(), job_id),
    )
    connection.commit()
    connection.close()


def update_processing_progress(job_id: str, progress: int, total: int, device: str) -> None:
    connection = get_db()
    connection.execute(
        "UPDATE jobs SET phase='processing', progress=?, total_samples=?, device=?, updated_at=? "
        "WHERE id=?",
        (progress, total, device, utc_now(), job_id),
    )
    connection.commit()
    connection.close()


def complete_job(
    job_id: str,
    video_id: str,
    results: list[tuple[float, float, str, float]],
    processed: int,
    total: int,
    device: str,
) -> None:
    max_timing_error_ms = max(
        (abs(actual - scheduled) * 1000 for scheduled, actual, _, _ in results),
        default=0.0,
    )
    connection = get_db()
    connection.execute("DELETE FROM results WHERE job_id=?", (job_id,))
    connection.executemany(
        "INSERT INTO results(job_id, video_id, timestamp_seconds, scheduled_timestamp_seconds, "
        "red, green, blue, class_label, confidence) VALUES(?,?,?,?,?,?,?,?,?)",
        [
            (job_id, video_id, actual, scheduled, 0.0, 0.0, 0.0, label, confidence)
            for scheduled, actual, label, confidence in results
        ],
    )
    connection.execute(
        "UPDATE jobs SET status='completed', phase='completed', progress=?, total_samples=?, "
        "collected_samples=?, max_timing_error_ms=?, device=?, updated_at=? WHERE id=?",
        (processed, total, total, max_timing_error_ms, device, utc_now(), job_id),
    )
    connection.execute("UPDATE videos SET current_job_id=? WHERE id=?", (job_id, video_id))
    connection.commit()
    connection.close()


def fail_job(job_id: str, error: str) -> None:
    connection = get_db()
    connection.execute(
        "UPDATE jobs SET status='failed', phase='failed', error=?, updated_at=? WHERE id=?",
        (error, utc_now(), job_id),
    )
    connection.commit()
    connection.close()



def bind_shared_media(video_id: str, path: Path) -> None:
    """Persist shared ownership so deletion remains safe even with sharing disabled."""
    connection = get_db()
    try:
        with connection:
            connection.execute("UPDATE videos SET path=?, shared_media=1 WHERE id=?", (str(path), video_id))
    finally:
        connection.close()


def video_is_shared(video_id: str) -> bool:
    """Return whether a video references a catalog-owned immutable media file."""
    connection = get_db()
    try:
        row = connection.execute("SELECT shared_media FROM videos WHERE id=?", (video_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Video not found")
        return bool(row["shared_media"])
    finally:
        connection.close()


def create_online_video(video_id: str, metadata: dict[str, Any], start_seconds: float | None = None, end_seconds: float | None = None) -> dict[str, Any]:
    """Create a remote review with timestamps relative to its selected source range."""
    start = start_seconds or 0.0
    end = end_seconds if end_seconds is not None else float(metadata['duration'])
    if start >= end or end > float(metadata['duration']):
        raise HTTPException(status_code=400, detail="Review range must lie within the source video")
    connection = get_db()
    try:
        with connection:
            connection.execute(
                "INSERT INTO videos(id,original_name,path,mime_type,duration,width,height,created_at,mode,source_url,source_id,source_start_seconds,source_end_seconds,source_quality) VALUES(?,?,NULL,'video/mp4',?,?,?,?, 'online',?,?,?,?,?)",
                (video_id, metadata['original_name'], end-start, metadata['width'], metadata['height'], utc_now(), metadata['source_url'], metadata['source_id'], start, end, metadata.get('source_quality', '720p')),
            )
        row = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        return serialize_video(connection, row)
    finally:
        connection.close()


def set_video_mode(video_id: str, mode: str) -> dict[str, Any]:
    """Persist an available playback mode while refusing active analysis changes."""
    if mode not in {'online', 'offline'}:
        raise HTTPException(status_code=400, detail="Invalid playback mode")
    connection = get_db()
    try:
        with connection:
            row = connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Video not found")
            if connection.execute("SELECT 1 FROM jobs WHERE video_id=? AND status IN ('queued','running')", (video_id,)).fetchone():
                raise HTTPException(status_code=409, detail="Wait for analysis to finish before changing modes")
            if mode == 'online' and not row['source_id']:
                raise HTTPException(status_code=409, detail="This review has no supported online source")
            if mode == 'offline' and (not row['path'] or not Path(row['path']).is_file()):
                raise HTTPException(status_code=409, detail="Download a local copy before switching to Offline")
            connection.execute("UPDATE videos SET mode=? WHERE id=?", (mode, video_id))
        return serialize_video(connection, connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    finally:
        connection.close()


def bind_local_copy(video_id: str, path: Path, mime_type: str, width: int, height: int, shared_media: bool = False) -> dict[str, Any]:
    """Attach downloaded media while preserving review identity, crop and analysis."""
    connection = get_db()
    try:
        with connection:
            if not connection.execute("SELECT 1 FROM videos WHERE id=?", (video_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Video not found")
            connection.execute("UPDATE videos SET path=?,mime_type=?,width=?,height=?,shared_media=? WHERE id=?", (str(path), mime_type, width, height, int(shared_media), video_id))
        return serialize_video(connection, connection.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone())
    finally:
        connection.close()


def update_source_metadata(video_id: str, url: str, start_seconds: float | None = None, end_seconds: float | None = None,
                           quality: str = "720p") -> None:
    """Track supported source identity for a newly completed ordinary download."""
    source = _online_source(url)
    if not source:
        return
    source_id, source_url = source
    connection = get_db()
    try:
        with connection:
            # Freeze the observed range even when the import had no explicit end.
            # Later edits to the upstream video must not silently extend a review.
            connection.execute("UPDATE videos SET source_url=?,source_id=?,source_start_seconds=?,source_end_seconds=COALESCE(?, ? + duration),source_quality=? WHERE id=?", (source_url, source_id, start_seconds or 0, end_seconds, start_seconds or 0, quality, video_id))
    finally:
        connection.close()


def store_partial_results(job_id: str, results: list[tuple[float, float, str, float]]) -> None:
    """Replace one job's cumulative provisional rows without changing completed results."""
    connection = get_db()
    try:
        with connection:
            job = connection.execute("SELECT video_id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="Analysis job not found")
            connection.execute("DELETE FROM results WHERE job_id=?", (job_id,))
            connection.executemany("INSERT INTO results(job_id,video_id,timestamp_seconds,scheduled_timestamp_seconds,class_label,confidence) VALUES(?,?,?,?,?,?)", [(job_id, job['video_id'], actual, scheduled, label, confidence) for scheduled, actual, label, confidence in results])
    finally:
        connection.close()


def update_online_progress(job_id: str, phase: str, processed: int, total: int, device: str | None = None) -> None:
    """Publish sparse scan/refinement progress through the normal job response."""
    connection = get_db()
    try:
        with connection:
            connection.execute("UPDATE jobs SET phase=?,progress=?,collected_samples=?,total_samples=?,device=COALESCE(?,device),updated_at=? WHERE id=?", (phase, processed, processed, total, device, utc_now(), job_id))
    finally:
        connection.close()
