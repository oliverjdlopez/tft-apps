from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

from db import session as db_session


class _SchemaInspector:
    def __init__(self, columns: set[str]) -> None:
        self.columns = columns

    def has_table(self, table_name: str, *, schema) -> bool:
        return table_name == "player_units"

    def get_columns(self, table_name: str, *, schema):
        assert table_name == "player_units"
        return [{"name": name} for name in self.columns]


class _FakePostgresBind:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement) -> None:
        self.statements.append(str(statement))


def test_open_db_initializes_one_engine_and_schema_across_threads(monkeypatch) -> None:
    target = f"postgresql:///thread-test-{uuid4().hex}"
    engine = create_engine("sqlite:///:memory:")
    calls = {"engine": 0, "prepare": 0, "schema": 0, "indexes": 0}
    calls_lock = threading.Lock()

    def record(name: str) -> None:
        with calls_lock:
            calls[name] += 1
        time.sleep(0.01)

    def create_engine_once(_target: str):
        record("engine")
        return engine

    monkeypatch.setattr(db_session, "_create_engine", create_engine_once)
    monkeypatch.setattr(
        db_session,
        "_prepare_schema_names",
        lambda _engine: record("prepare"),
    )
    monkeypatch.setattr(
        db_session,
        "_ensure_model_indexes",
        lambda _engine: record("indexes"),
    )

    def open_and_close() -> None:
        session = db_session.open_db(
            target,
            create_schema=lambda _engine: record("schema"),
        )
        session.close()

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _index: open_and_close(), range(16)))

        assert calls == {"engine": 1, "prepare": 1, "schema": 1, "indexes": 1}
    finally:
        db_session._ENGINES.pop(target, None)
        db_session._SCHEMA_READY.discard(target)
        engine.dispose()


def test_unit_cost_migration_updates_both_tables_once() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE player_units (rarity INTEGER NOT NULL)"))
            conn.execute(text("CREATE TABLE unit_stats (rarity INTEGER)"))
            conn.execute(text("INSERT INTO player_units VALUES (3)"))
            conn.execute(text("INSERT INTO unit_stats VALUES (4)"))

            assert db_session.migrate_unit_cost_columns(conn, schema=None) == 2
            assert conn.execute(text("SELECT cost FROM player_units")).scalar_one() == 4
            assert conn.execute(text("SELECT cost FROM unit_stats")).scalar_one() == 5
            assert db_session.migrate_unit_cost_columns(conn, schema=None) == 0
            assert conn.execute(text("SELECT cost FROM player_units")).scalar_one() == 4
    finally:
        engine.dispose()


def test_unit_cost_migration_rejects_partial_schema() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE player_units (rarity INTEGER NOT NULL, cost INTEGER)"
                )
            )

            with pytest.raises(RuntimeError, match="both legacy `rarity` and current `cost`"):
                db_session.migrate_unit_cost_columns(conn, schema=None)
    finally:
        engine.dispose()


def test_postgres_cost_migration_rechecks_after_process_lock(monkeypatch) -> None:
    inspectors = iter([_SchemaInspector({"rarity"}), _SchemaInspector({"cost"})])
    monkeypatch.setattr(db_session, "inspect", lambda _target: next(inspectors))
    bind = _FakePostgresBind()

    assert db_session.migrate_unit_cost_columns(bind, schema="public") == 0
    assert len(bind.statements) == 1
    assert "pg_advisory_xact_lock" in bind.statements[0]


def test_postgres_cost_migration_skips_lock_after_schema_is_current(monkeypatch) -> None:
    monkeypatch.setattr(
        db_session,
        "inspect",
        lambda _target: _SchemaInspector({"cost"}),
    )
    bind = _FakePostgresBind()

    assert db_session.migrate_unit_cost_columns(bind, schema="public") == 0
    assert bind.statements == []
