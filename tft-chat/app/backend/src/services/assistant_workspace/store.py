"""Checkout-owned immutable draft revisions and durable run receipts."""
from __future__ import annotations
import json
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path
import sqlite3
import time
from typing import Any
import uuid


class Store:
    """Persist editable heads, immutable revisions, history, and results."""
    def __init__(self, root: Path):
        """Initialize only this checkout's ignored workspace database."""
        root.mkdir(parents=True, exist_ok=True)
        self.root = root
        self.path = root / 'workspace.sqlite3'
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS heads (assistant TEXT PRIMARY KEY, revision TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, assistant TEXT NOT NULL, created REAL NOT NULL, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, assistant TEXT NOT NULL, action TEXT NOT NULL, revision TEXT, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, assistant TEXT NOT NULL, revision TEXT NOT NULL, kind TEXT NOT NULL, state TEXT NOT NULL, created REAL NOT NULL, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open one independent transaction with a bounded busy timeout."""
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def revision(self, identity: str) -> dict:
        """Read a saved revision without changing its contents."""
        with self.connect() as db:
            row = db.execute('SELECT value FROM revisions WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        return json.loads(row['value'])

    def head(self, assistant: str) -> dict | None:
        """Read the sole editable head, if one exists."""
        with self.connect() as db:
            row = db.execute('SELECT revision FROM heads WHERE assistant=?', (assistant,)).fetchone()
        return self.revision(row['revision']) if row else None

    def save(self, assistant: str, value: dict) -> dict:
        """Append an immutable revision and move only this assistant's head."""
        revision = {**value, 'id': uuid.uuid4().hex, 'assistant': assistant, 'created': time.time()}
        with self.connect() as db:
            db.execute('INSERT INTO revisions VALUES (?,?,?,?)', (revision['id'], assistant, revision['created'], json.dumps(revision)))
            db.execute('INSERT OR REPLACE INTO heads VALUES (?,?)', (assistant, revision['id']))
        return revision

    def close(self, assistant: str, action: str) -> None:
        """Close a draft while retaining every saved revision and run."""
        head = self.head(assistant)
        with self.connect() as db:
            db.execute('DELETE FROM heads WHERE assistant=?', (assistant,))
            db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (uuid.uuid4().hex, assistant, action, head['id'] if head else None, time.time()))

    def history(self, assistant: str) -> dict:
        """Return immutable revisions and apply/discard events for one assistant."""
        with self.connect() as db:
            revisions = [json.loads(row['value']) for row in db.execute('SELECT value FROM revisions WHERE assistant=? ORDER BY created DESC', (assistant,))]
            events = [dict(row) for row in db.execute('SELECT * FROM events WHERE assistant=? ORDER BY created DESC', (assistant,))]
        return {'revisions': revisions, 'events': events}

    def run(self, identity: str) -> dict | None:
        """Return a durable result receipt or an absent submission."""
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (identity,)).fetchone()
        return {**dict(row), 'value': json.loads(row['value'])} if row else None

    def put_run(self, identity: str, assistant: str, revision: str, kind: str, state: str, value: dict) -> dict:
        """Checkpoint a submitted operation, preserving its frozen lineage."""
        previous = self.run(identity)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?)',
                       (identity, assistant, revision, kind, state, previous['created'] if previous else time.time(), json.dumps(value)))
        return self.run(identity)

    def runs(self, assistant: str) -> list[dict]:
        """Return saved trial and experiment receipts, newest first."""
        with self.connect() as db:
            ids = [row['id'] for row in db.execute('SELECT id FROM runs WHERE assistant=? ORDER BY created DESC', (assistant,))]
        return [self.run(identity) for identity in ids]

    def interrupt_trials(self) -> None:
        """Make restarted executions explicit without repeating model calls."""
        with self.connect() as db:
            db.execute("UPDATE runs SET state='interrupted' WHERE kind='trial' AND state IN ('queued','running')")
