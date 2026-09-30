from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import sessionmaker

from agents.tool_context import ToolContext
from db import session as db_session
from domain.tools.db_tools import utils as tool_utils


def _completion_records(caplog) -> list[dict[str, object]]:
    return [
        json.loads(record.message.removeprefix("analysis_db_call "))
        for record in caplog.records
        if record.message.startswith("analysis_db_call ")
    ]


def _run_in_state(tool: str, call_id: str, fn):
    ctx = ToolContext(
        None,
        tool_name=tool,
        tool_call_id=call_id,
        tool_arguments="{}",
    )
    return asyncio.run(tool_utils.run_db_tool(ctx, fn))


def test_concurrent_calls_use_distinct_sessions_and_connections(
    monkeypatch, tmp_path: Path
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'pool.db'}",
        pool_size=2,
        max_overflow=0,
        connect_args={"check_same_thread": False},
    )
    db_session._instrument_pool(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(tool_utils, "open_db", factory)
    barrier = threading.Barrier(2)

    def read(session):
        connection = session.connection()
        ids = (id(session), id(connection.connection.dbapi_connection))
        barrier.wait(timeout=2)
        session.execute(text("select 1"))
        return ids

    async def run_both():
        async def one(call_id: str):
            ctx = ToolContext(
                None,
                tool_name="compare_cohorts",
                tool_call_id=call_id,
                tool_arguments="{}",
            )
            return await tool_utils.run_db_tool(ctx, read)

        return await asyncio.gather(one("call-a"), one("call-b"))

    try:
        first, second = asyncio.run(run_both())
        assert first[0] != second[0]
        assert first[1] != second[1]
        assert db_session.pool_state(engine)["checked_out"] == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("failure", "outcome"),
    [("success", "success"), ("query_timeout", "database_timeout"), ("exception", "other_error")],
)
def test_checkout_checkin_balanced_for_completed_outcomes(
    monkeypatch, caplog, failure: str, outcome: str
) -> None:
    engine = create_engine("sqlite:///:memory:")
    db_session._instrument_pool(engine)
    monkeypatch.setattr(tool_utils, "open_db", sessionmaker(bind=engine))
    caplog.set_level(logging.INFO, logger="tft.analysis.db")

    class Cancelled(Exception):
        sqlstate = "57014"

    def read(session):
        session.execute(text("select 1"))
        if failure == "query_timeout":
            raise DBAPIError("hidden sql", {}, Cancelled())
        if failure == "exception":
            raise RuntimeError("secret-player-id")
        return {"ok": True}

    try:
        if failure == "exception":
            with pytest.raises(RuntimeError):
                _run_in_state("rank_units", f"call-{failure}", read)
        else:
            result = _run_in_state("rank_units", f"call-{failure}", read)
            if failure == "query_timeout":
                assert result["kind"] == "error"
                assert result["error"]["code"] == "database_timeout"
                assert result["error"]["retryable"] is True
        record = _completion_records(caplog)[-1]
        assert record["outcome"] == outcome
        assert record["checkouts"] == record["checkins"] == 1
        assert record["acquisition_ms"] >= 0
        assert record["execution_ms"] >= 0
        assert "hidden sql" not in caplog.text
        assert "secret-player-id" not in caplog.text
    finally:
        engine.dispose()


def test_pool_timeout_is_retryable_and_logged_without_checkout(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        tool_utils,
        "open_db",
        lambda: (_ for _ in ()).throw(PoolTimeoutError("credentials secret")),
    )
    caplog.set_level(logging.INFO, logger="tft.analysis.db")

    result = _run_in_state("resolve_tft_names", "pool-call", lambda _session: {})

    assert result == {
        "kind": "error",
        "context": {},
        "error": {
            "code": "database_pool_timeout",
            "message": "Database connection pool checkout timed out; retry the analysis.",
            "retryable": True,
            "timeout_seconds": 5.0,
        },
        "warnings": [],
    }
    record = _completion_records(caplog)[-1]
    assert record["outcome"] == "pool_timeout"
    assert record["checkouts"] == record["checkins"] == 0
    assert "credentials secret" not in caplog.text


def test_cancelled_call_returns_standard_error(monkeypatch) -> None:
    """Translate caller cancellation without leaking the worker session."""
    engine = create_engine("sqlite:///:memory:")
    monkeypatch.setattr(tool_utils, "open_db", sessionmaker(bind=engine))
    started = threading.Event()
    release = threading.Event()

    def read(_session):
        started.set()
        release.wait(timeout=2)
        return {"kind": "table"}

    async def cancel_call():
        ctx = ToolContext(
            None,
            tool_name="rank_units",
            tool_call_id="cancel-call",
            tool_arguments="{}",
        )
        task = asyncio.create_task(tool_utils.run_db_tool(ctx, read))
        await asyncio.to_thread(started.wait, 1)
        task.cancel()
        result = await task
        release.set()
        return result

    try:
        result = asyncio.run(cancel_call())
        assert result["kind"] == "error"
        assert result["error"]["code"] == "cancelled"
        assert result["error"]["retryable"] is True
    finally:
        release.set()
        engine.dispose()


def test_postgres_setup_applies_timeout_before_analysis(monkeypatch) -> None:
    statements: list[str] = []

    class Connection:
        dialect = type("Dialect", (), {"name": "postgresql"})()

    class Session:
        bind = None

        def connection(self):
            return Connection()

        def execute(self, statement):
            statements.append(str(statement))

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(tool_utils, "open_db", Session)
    _run_in_state("compare_cohorts", "timeout-call", lambda _session: {"ok": True})

    assert statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = 40000",
    ]


def test_postgres_engine_bounds_connect_and_pool_checkout(monkeypatch) -> None:
    captured = {}
    fake_engine = object()

    def create(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return fake_engine

    monkeypatch.setattr(db_session, "create_engine", create)
    monkeypatch.setattr(db_session, "_instrument_pool", lambda engine: None)
    monkeypatch.setattr(db_session, "_rds_iam_target", lambda target: None)

    assert db_session._create_engine("postgresql:///analysis") is fake_engine
    assert captured["pool_timeout"] == 5
    assert captured["connect_args"] == {"connect_timeout": 5}
