"""Short SQLite transactions for immutable transcript task attempts."""
from contextlib import closing
import json
import sqlite3
import uuid

try:
    from .. import db
except ImportError:
    import db


def init_schema(connection: sqlite3.Connection) -> None:
    """Initialize history and enforce one queued/running attempt per source/task."""
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS transcript_task_runs (
            id TEXT PRIMARY KEY, transcription_task_id TEXT NOT NULL,
            task_name TEXT NOT NULL, task_version INTEGER NOT NULL,
            transcript_hash TEXT NOT NULL, status TEXT NOT NULL,
            output_json TEXT, error_code TEXT, error TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS transcript_task_history
            ON transcript_task_runs(transcription_task_id, task_name, created_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS transcript_task_active
            ON transcript_task_runs(transcription_task_id, task_name)
            WHERE status IN ('queued', 'running');
    """)


def serialize(row: sqlite3.Row) -> dict:
    """Decode persisted output while preserving all run provenance."""
    result = dict(row)
    result["output"] = json.loads(result.pop("output_json")) if row["output_json"] is not None else None
    return result


def get(run_id: str) -> dict:
    """Read a saved attempt even while the upstream service is unavailable."""
    with closing(db.get_db()) as connection, connection:
        row = connection.execute("SELECT * FROM transcript_task_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(404, "Transcript task run not found")
    return serialize(row)


def runs(source_id: str, digest: str) -> list[dict]:
    """Read current-source history in newest-first insertion order."""
    with closing(db.get_db()) as connection, connection:
        return [serialize(r) for r in connection.execute("SELECT * FROM transcript_task_runs WHERE transcription_task_id=? AND transcript_hash=? ORDER BY created_at DESC, rowid DESC", (source_id, digest))]


def choose(source_id: str, name: str, version: int, digest: str, rerun: bool, create: bool = True) -> tuple[dict | None, bool]:
    """Atomically reuse active/successful work or insert a fresh queued attempt."""
    connection = db.get_db()
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM transcript_task_runs WHERE transcription_task_id=? AND task_name=? AND status IN ('queued','running') LIMIT 1", (source_id, name)).fetchone()
        if row is None and not rerun:
            row = connection.execute("SELECT * FROM transcript_task_runs WHERE transcription_task_id=? AND task_name=? AND task_version=? AND transcript_hash=? AND status='completed' ORDER BY created_at DESC,rowid DESC LIMIT 1", (source_id, name, version, digest)).fetchone()
        if row is not None:
            connection.commit()
            return serialize(row), False
        if not create:
            connection.commit()
            return None, False
        run_id, now = uuid.uuid4().hex, db.utc_now()
        connection.execute("INSERT INTO transcript_task_runs(id,transcription_task_id,task_name,task_version,transcript_hash,status,created_at,updated_at) VALUES(?,?,?,?,?,'queued',?,?)", (run_id, source_id, name, version, digest, now, now))
        connection.commit()
        return get(run_id), True
    finally:
        connection.close()


def update(run_id: str, status: str, *, output=None, error_code=None, error=None) -> None:
    """Finish or advance one attempt without overwriting earlier successful rows."""
    with closing(db.get_db()) as connection, connection:
        connection.execute("UPDATE transcript_task_runs SET status=?,output_json=?,error_code=?,error=?,updated_at=? WHERE id=?", (status, json.dumps(output, ensure_ascii=False) if output is not None else None, error_code, error, db.utc_now(), run_id))


def recover() -> None:
    """Make interrupted work explicitly retryable after a backend restart."""
    with closing(db.get_db()) as connection, connection:
        connection.execute("UPDATE transcript_task_runs SET status='failed',error_code='interrupted',error='Interrupted by backend restart. Retry manually to start a new attempt.',updated_at=? WHERE status IN ('queued','running')", (db.utc_now(),))
