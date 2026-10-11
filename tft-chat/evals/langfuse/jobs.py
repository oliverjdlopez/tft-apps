"""Durable job operations for the single-consumer local experiment service."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any


class JobStore:
    """Own SQLite transactions that preserve accepted jobs across restarts."""

    def __init__(self, root: Path):
        """Initialize only the service's dedicated runtime directory."""
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "jobs.sqlite3"
        with self.connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL,
                snapshot TEXT NOT NULL, bundle TEXT NOT NULL, result TEXT,
                error TEXT, updated REAL NOT NULL)""")
            connection.execute('''CREATE TABLE IF NOT EXISTS workspace_submissions (
                id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, value TEXT NOT NULL)''')

    def submission(self, identity: str) -> dict | None:
        """Read a persistent submission receipt before preparing another run."""
        with self.connect() as connection:
            row = connection.execute('SELECT request_hash,value FROM workspace_submissions WHERE id=?', (identity,)).fetchone()
        return {'request_hash': row['request_hash'], **json.loads(row['value'])} if row else None

    def put_submission(self, identity: str, request_hash: str, value: dict) -> None:
        """Persist preparation intent or failure without scheduling execution."""
        with self.connect() as connection:
            connection.execute('INSERT OR REPLACE INTO workspace_submissions VALUES (?,?,?)', (identity, request_hash, json.dumps(value)))

    def connect(self) -> sqlite3.Connection:
        """Open an independent connection for one atomic operation."""
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def has_pending(self) -> bool:
        """Report jobs whose execution or grading must finish before setup changes."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM jobs WHERE state IN ('queued','running','awaiting_scores') LIMIT 1"
            ).fetchone()
        return row is not None

    def submit(self, bundle: dict[str, Any], snapshot: str, *, exported: bool = False, awaiting_result: dict | None = None, submission_id: str | None = None) -> str:
        """Persist a run or terminal export atomically before acknowledging the UI."""
        job_id = uuid.uuid4().hex
        now = time.time()
        with self.connect() as connection:
            connection.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (
                job_id, "awaiting_scores" if awaiting_result is not None else "exported" if exported else "queued", now, snapshot, json.dumps(bundle),
                json.dumps(awaiting_result) if awaiting_result is not None else json.dumps({"snapshot": snapshot}) if exported else None, None, now,
            ))
            if submission_id:
                receipt = {'state': 'queued', 'job_id': job_id, 'snapshot': snapshot, 'status_url': f'/jobs/{job_id}'}
                connection.execute('UPDATE workspace_submissions SET value=? WHERE id=?', (json.dumps(receipt), submission_id))
        return job_id

    def claim(self) -> dict[str, Any] | None:
        """Atomically claim the oldest queued job for the sole consumer."""
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                return None
            connection.execute("UPDATE jobs SET state='running',updated=? WHERE id=?", (time.time(), row["id"]))
            job = dict(row)
            job["bundle"] = json.loads(job["bundle"])
            return job

    def finish(self, job_id: str, state: str, *, result: dict | None = None, error: str | None = None) -> None:
        """Record completion or explicit failure without resubmitting work."""
        if state not in {"completed", "failed", "interrupted", "exported"}:
            raise ValueError("Invalid terminal job state")
        with self.connect() as connection:
            row = connection.execute("SELECT bundle FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is not None and state in {"completed", "failed"}:
                bundle = json.loads(row["bundle"])
                if "items" in bundle and "suite" in bundle:
                    from .artifacts import write_run_artifact
                    if result is None:
                        result = {"passed": False, "experiments": []}
                    write_run_artifact(bundle, result, self.path.parent / "artifacts", job_id,
                                       state=state, error=error)
            connection.execute("UPDATE jobs SET state=?,result=?,error=?,updated=? WHERE id=?", (
                state, json.dumps(result) if result is not None else None, error, time.time(), job_id,
            ))

    def awaiting_scores(self, job_id: str, result: dict) -> None:
        """Checkpoint completed execution before any asynchronous grading reads."""
        with self.connect() as connection:
            connection.execute("UPDATE jobs SET state='awaiting_scores',result=?,updated=? WHERE id=?",
                               (json.dumps(result), time.time(), job_id))

    def pending_scores(self) -> list[dict]:
        """Resume score reconciliation after restart without repeating execution."""
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs WHERE state='awaiting_scores' ORDER BY created").fetchall()
        return [{**dict(row), 'bundle': json.loads(row['bundle']), 'result': json.loads(row['result'])} for row in rows]

    def recover(self) -> list[str]:
        """Mark work interrupted by a prior process; never repeat paid calls."""
        with self.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT id FROM jobs WHERE state='running'")]
            connection.execute("UPDATE jobs SET state='interrupted',error=?,updated=? WHERE state='running'", (
                "Service restarted during execution; replay explicitly from the UI", time.time(),
            ))
        return ids

    def get(self, job_id: str) -> dict[str, Any] | None:
        """Return status without exposing the full potentially large dataset."""
        with self.connect() as connection:
            row = connection.execute("SELECT id,state,created,snapshot,result,error,updated FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        if result["result"]:
            result["result"] = json.loads(result["result"])
        return result
