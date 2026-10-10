from __future__ import annotations

import os
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
            id TEXT PRIMARY KEY, original_name TEXT NOT NULL, path TEXT NOT NULL,
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
            id TEXT PRIMARY KEY, video_id TEXT, media_path TEXT NOT NULL,
            status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            transcript TEXT, language TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(id)
        );
        CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_results_job_time ON results(job_id, timestamp_seconds);
        """
    )
    video_columns = {row["name"] for row in connection.execute("PRAGMA table_info(videos)")}
    if "shared_media" not in video_columns:
        connection.execute("ALTER TABLE videos ADD COLUMN shared_media INTEGER NOT NULL DEFAULT 0")
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
    result_columns = {row["name"] for row in connection.execute("PRAGMA table_info(results)").fetchall()}
    if "scheduled_timestamp_seconds" not in result_columns:
        connection.execute("ALTER TABLE results ADD COLUMN scheduled_timestamp_seconds REAL")
    if "class_label" not in result_columns:
        connection.execute("ALTER TABLE results ADD COLUMN class_label TEXT")
    if "confidence" not in result_columns:
        connection.execute("ALTER TABLE results ADD COLUMN confidence REAL")
    download_columns = {row["name"] for row in connection.execute("PRAGMA table_info(download_tasks)").fetchall()}
    for column, declaration in (
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


def video_path(video_id: str) -> Path:
    connection = get_db()
    row = connection.execute("SELECT path FROM videos WHERE id=?", (video_id,)).fetchone()
    connection.close()
    if not row:
        raise HTTPException(status_code=404, detail="Video not found")
    return Path(row["path"])


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
) -> dict[str, Any]:
    now = utc_now()
    connection = get_db()
    connection.execute(
        "INSERT INTO download_tasks(id, status, progress, url, start_seconds, end_seconds, "
        "checkpoint_interval_seconds, quality, target_fps, media_type, transcribe, created_at, updated_at) "
        "VALUES(?, 'queued', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (task_id, url, start_seconds, end_seconds, checkpoint_interval_seconds, quality, target_fps, media_type, int(transcribe), now, now),
    )
    connection.commit()
    connection.close()
    return {"task_id": task_id, "status": "queued", "progress": 0.0, "video": None, "error": None}


def get_download_request(task_id: str) -> dict[str, Any]:
    connection = get_db()
    row = connection.execute(
        "SELECT url, start_seconds, end_seconds, checkpoint_interval_seconds, quality, target_fps, media_type, transcribe FROM download_tasks WHERE id=?",
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


def update_transcription_task(task_id: str, *, status: str | None = None, transcript: str | None = None, language: str | None = None, error: str | None = None) -> None:
    assignments = ["updated_at=?"]
    values: list[Any] = [utc_now()]
    for column, value in (("status", status), ("transcript", transcript), ("language", language), ("error", error)):
        if value is not None:
            assignments.append(f"{column}=?")
            values.append(value)
    values.append(task_id)
    connection = get_db()
    connection.execute(f"UPDATE transcription_tasks SET {', '.join(assignments)} WHERE id=?", values)
    connection.commit()
    connection.close()


def get_transcription_task(task_id: str, connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    owns_connection = connection is None
    connection = connection or get_db()
    row = connection.execute("SELECT * FROM transcription_tasks WHERE id=?", (task_id,)).fetchone()
    if owns_connection:
        connection.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Transcription task not found")
    return {"task_id": row["id"], "video_id": row["video_id"], "status": row["status"], "transcript": row["transcript"], "language": row["language"], "error": row["error"]}


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
        "AND checkpoint_interval_seconds IS NOT NULL "
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


def delete_video(video_id: str) -> Path:
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
    return Path(row["path"])


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
        if source["sample_interval_seconds"] != sample_interval_seconds:
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
        "box_x, box_y, box_width, box_height, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
