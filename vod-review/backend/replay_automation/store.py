"""SQLite persistence and transactional claims for one owned automation runtime."""

from contextlib import closing
from datetime import datetime, timedelta
import json
import uuid

from fastapi import HTTPException

try:
    from .. import db
except ImportError:  # Backend-directory uvicorn launch.
    import db
from .models import ReplaySchedule
from .utils import latest_occurrence, media_identity, next_occurrence


def initialize() -> None:
    """Create ignored app-local state and recover interrupted automation runs."""
    with closing(db.get_db()) as connection, connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS replay_schedule (
                id INTEGER PRIMARY KEY CHECK(id=1), settings TEXT NOT NULL, next_run_at TEXT
            );
            CREATE TABLE IF NOT EXISTS replay_runs (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, scheduled_at TEXT NOT NULL,
                window_start TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                matched INTEGER NOT NULL DEFAULT 0, imported INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0, errors TEXT NOT NULL DEFAULT '[]',
                settings TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS replay_single_active_run
                ON replay_runs(status) WHERE status='running';
            CREATE TABLE IF NOT EXISTS replay_imports (
                media_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, title TEXT NOT NULL,
                url TEXT NOT NULL, source_url TEXT NOT NULL, published_at TEXT NOT NULL,
                task_id TEXT, video_id TEXT, status TEXT NOT NULL
            );
        """)
        connection.execute("INSERT OR IGNORE INTO replay_schedule VALUES(1, ?, NULL)", (ReplaySchedule().model_dump_json(),))
        connection.execute("UPDATE replay_runs SET status='interrupted', finished_at=? WHERE status='running'", (db.utc_now(),))
        # Existing downloads are recovered by init_db; keep completed associations
        # even if the service stopped between finishing a download and recording it.
        connection.execute("""UPDATE replay_imports SET
            video_id=(SELECT video_id FROM download_tasks WHERE id=replay_imports.task_id),
            status=CASE WHEN EXISTS(SELECT 1 FROM download_tasks WHERE id=replay_imports.task_id AND status='completed')
                THEN 'completed' ELSE 'interrupted' END WHERE status='downloading'""")


def get_settings() -> tuple[ReplaySchedule, str | None]:
    """Read the saved settings and next scheduled instant."""
    with closing(db.get_db()) as connection:
        row = connection.execute("SELECT * FROM replay_schedule WHERE id=1").fetchone()
        return ReplaySchedule.model_validate_json(row["settings"]), row["next_run_at"]


def save_settings(settings: ReplaySchedule, now: datetime) -> None:
    """Apply changes to subsequent runs; an already claimed run keeps its snapshot."""
    next_run = next_occurrence(now, settings.daily_time, settings.timezone).isoformat() if settings.enabled else None
    with closing(db.get_db()) as connection, connection:
        connection.execute("UPDATE replay_schedule SET settings=?, next_run_at=? WHERE id=1", (settings.model_dump_json(), next_run))


def claim_run(now: datetime, manual: bool = False) -> dict | None:
    """Atomically claim a due run so polling and Run now cannot overlap."""
    with closing(db.get_db()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM replay_schedule WHERE id=1").fetchone()
        settings = ReplaySchedule.model_validate_json(row["settings"])
        if not manual and (not settings.enabled or not row["next_run_at"] or row["next_run_at"] > now.isoformat()):
            return None
        if not settings.sources:
            raise HTTPException(400, "Save at least one creator before running discovery")
        if connection.execute("SELECT 1 FROM replay_runs WHERE status='running'").fetchone():
            if manual:
                raise HTTPException(409, "Creator discovery is already running")
            return None
        scheduled = now if manual else latest_occurrence(now, settings.daily_time, settings.timezone)
        run = {"id": uuid.uuid4().hex, "status": "running", "scheduled_at": scheduled.isoformat(),
               "window_start": (scheduled - timedelta(hours=settings.window_hours)).isoformat(),
               "started_at": now.isoformat(), "settings": settings.model_dump()}
        connection.execute("INSERT INTO replay_runs(id,status,scheduled_at,window_start,started_at,settings) VALUES(?,?,?,?,?,?)",
                           (*[run[key] for key in ("id", "status", "scheduled_at", "window_start", "started_at")], settings.model_dump_json()))
        if not manual:
            connection.execute("UPDATE replay_schedule SET next_run_at=? WHERE id=1", (next_occurrence(now, settings.daily_time, settings.timezone).isoformat(),))
        return run


def update_run(run_id: str, *, matched: int, imported: int, skipped: int, errors: list[dict], status: str = "running") -> None:
    """Persist progress and source/download errors without obscuring successful imports."""
    with closing(db.get_db()) as connection, connection:
        connection.execute("UPDATE replay_runs SET matched=?,imported=?,skipped=?,errors=?,status=?,finished_at=? WHERE id=?",
                           (matched, imported, skipped, json.dumps(errors), status, db.utc_now() if status != "running" else None, run_id))


def reserve_import(replay: dict, run_id: str) -> bool:
    """Skip existing full video imports and atomically reserve each provider media ID."""
    with closing(db.get_db()) as connection, connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM replay_imports WHERE media_id=?", (replay["id"],)).fetchone()
        if row and row["status"] == "downloading":
            return False
        if row and row["status"] == "completed":
            # Deleting a library video permits importing it again in a later window.
            if connection.execute("SELECT 1 FROM videos WHERE id=?", (row["video_id"],)).fetchone():
                return False
        manual_tasks = connection.execute("""SELECT url,status,video_id FROM download_tasks
            WHERE media_type='video' AND start_seconds IS NULL AND end_seconds IS NULL
            AND status IN ('queued','running','pausing','paused','completed')""").fetchall()
        for task in manual_tasks:
            if media_identity(task["url"] or "") == replay["id"]:
                if task["status"] != "completed" or connection.execute("SELECT 1 FROM videos WHERE id=?", (task["video_id"],)).fetchone():
                    return False
        connection.execute("""INSERT INTO replay_imports(media_id,run_id,title,url,source_url,published_at,status)
            VALUES(?,?,?,?,?,?,'downloading') ON CONFLICT(media_id) DO UPDATE SET
            run_id=excluded.run_id,status='downloading',task_id=NULL,video_id=NULL""",
            (replay["id"], run_id, replay["title"], replay["url"], replay["source_url"], replay["published_at"]))
        return True


def update_import(media_id: str, *, status: str, task_id: str | None = None, video_id: str | None = None) -> None:
    """Associate standard download progress and final video identity with discovered media."""
    with closing(db.get_db()) as connection, connection:
        connection.execute("UPDATE replay_imports SET status=?,task_id=COALESCE(?,task_id),video_id=COALESCE(?,video_id) WHERE media_id=?",
                           (status, task_id, video_id, media_id))


def status() -> dict:
    """Return schedule, recent runs, and standard download progress for the UI."""
    settings, next_run = get_settings()
    with closing(db.get_db()) as connection:
        runs = [dict(row) for row in connection.execute("SELECT * FROM replay_runs ORDER BY started_at DESC LIMIT 10")]
        for run in runs:
            run["errors"] = json.loads(run["errors"])
            del run["settings"]
        items = [dict(row) for row in connection.execute("""SELECT i.*,d.progress,d.error
            FROM replay_imports i LEFT JOIN download_tasks d ON d.id=i.task_id
            ORDER BY i.rowid DESC LIMIT 100""")]
    return {"settings": settings.model_dump(), "next_run_at": next_run, "runs": runs, "imports": items}
