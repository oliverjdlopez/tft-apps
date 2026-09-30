"""Shared fixtures for the isolated RDS_TEST_* database."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from agents.tool_context import ToolContext
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.build_query_tables import (
    build_item_query_table,
    build_match_query_table,
    build_trait_query_table,
    build_unit_query_table,
)
from db.models import (
    AllMatch,
    Base,
    ItemMetadata,
    PlayerBoard,
    PlayerItem,
    PlayerUnit,
)
from db.session import AnalysisCallState, reset_analysis_call, set_analysis_call
from domain.tools.db_tools import utils as db_tool_utils

DEFAULT_TEST_TIMEOUT_SECONDS = 60.0
TEST_TIMEOUT_ENV = "PYTEST_TEST_TIMEOUT_SECONDS"


class StalledTestTimeoutError(TimeoutError):
    """Report a test that exceeded its configured call-phase deadline."""


def _configured_test_timeout(item: pytest.Item) -> float | None:
    """Resolve a per-test marker or repository-default timeout.

    Args:
        item: Pytest item whose call phase is about to run.

    Returns:
        Positive timeout seconds, or ``None`` when explicitly disabled.

    Raises:
        pytest.UsageError: If the timeout is invalid.
    """
    marker = item.get_closest_marker("timeout")
    raw: object = (
        marker.args[0]
        if marker and marker.args
        else marker.kwargs.get("seconds")
        if marker
        else os.environ.get(TEST_TIMEOUT_ENV, str(DEFAULT_TEST_TIMEOUT_SECONDS))
    )
    try:
        seconds = float(raw)
    except (TypeError, ValueError) as exc:
        raise pytest.UsageError(f"test timeout must be numeric, got {raw!r}") from exc
    if seconds == 0:
        return None
    if seconds < 0 or seconds == float("inf") or seconds != seconds:
        raise pytest.UsageError(f"test timeout must be positive, got {raw!r}")
    return seconds


@contextmanager
def _test_timeout(seconds: float | None, *, label: str) -> Iterator[None]:
    """Interrupt a stalled test call on POSIX while preserving nested alarms.

    Args:
        seconds: Call-phase timeout or ``None`` to disable the guardrail.
        label: Test node identifier included in the failure message.

    Yields:
        Control to the test call.
    """
    supported = (
        seconds is not None
        and threading.current_thread() is threading.main_thread()
        and hasattr(signal, "SIGALRM")
        and hasattr(signal, "setitimer")
    )
    if not supported:
        yield
        return
    started = time.monotonic()
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.setitimer(signal.ITIMER_REAL, 0)

    def raise_timeout(_signum: int, _frame: object) -> None:
        """Raise at the currently executing Python frame for a useful traceback."""
        raise StalledTestTimeoutError(f"{label} exceeded {seconds:g} seconds")

    signal.signal(signal.SIGALRM, raise_timeout)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_delay > 0:
            elapsed = time.monotonic() - started
            signal.setitimer(
                signal.ITIMER_REAL,
                max(1e-6, previous_delay - elapsed),
                previous_interval,
            )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Iterator[None]:
    """Apply the timeout guardrail across fixture setup, call, and teardown."""
    with _test_timeout(_configured_test_timeout(item), label=item.nodeid):
        yield


def _test_target():
    from core.config import resolve_database_target

    return resolve_database_target("test")


@pytest.fixture(scope="session")
def _pg_schema():
    """Ensure the test database is reachable and its schema exists (once)."""
    try:
        target = _test_target()
        psycopg.connect(target.connect_url).close()
    except Exception as exc:  # noqa: BLE001 - any connect failure means "skip DB tests".
        pytest.skip(f"RDS_TEST_* database is not configured or reachable: {exc}")

    from db.session import open_db

    open_db(_test_target()).close()  # runs init_schema
    yield


@pytest.fixture
def clean_db(_pg_schema):
    """Truncate every table so each test starts from an empty database."""
    from db.session import reset_db

    reset_db(_test_target())
    yield


@pytest.fixture
def conn(clean_db):
    """A standalone connection to a freshly-truncated test database."""
    from db.session import open_db

    db = open_db(_test_target(), ensure_schema=False)
    try:
        yield db
    finally:
        db.close()


def _match(
    match_id: str,
    puuid: str,
    patch: str = "16.12",
    queue_id: int = 1100,
) -> AllMatch:
    """Build one legacy raw-match fixture row for projection tests."""
    return AllMatch(
        match_id=match_id,
        puuid=puuid,
        region="americas",
        platform="na1",
        game_datetime=1750000000000,
        game_length=1800.0,
        game_version=f"Version {patch}.456",
        patch=patch,
        queue_id=queue_id,
        tft_set_number=17,
        tft_set_core_name="TFTSet17",
        ingested_at=1750000000000,
    )


def _board(
    match_id: str,
    puuid: str,
    placement: int,
    traits: str = "",
) -> PlayerBoard:
    """Build one final-board fixture row."""
    return PlayerBoard(
        match_id=match_id,
        puuid=puuid,
        comp_name=None,
        comp_code=None,
        star_levels="22",
        traits=traits,
        placement=placement,
        level=9,
    )


def _unit(
    match_id: str,
    puuid: str,
    name: str,
    placement: int,
    star_level: int = 2,
    item1: str | None = None,
) -> PlayerUnit:
    """Build one final-board unit fixture row."""
    return PlayerUnit(
        match_id=match_id,
        puuid=puuid,
        unit_name=name,
        unit_idx=0,
        star_level=star_level,
        item1=item1,
        item2=None,
        item3=None,
        placement=placement,
        cost=5,
    )


def _item(
    match_id: str,
    puuid: str,
    name: str,
    holder: str,
    placement: int,
) -> PlayerItem:
    """Build one final-board item fixture row."""
    return PlayerItem(
        match_id=match_id,
        puuid=puuid,
        item_name=name,
        unit_name=holder,
        idx=0,
        placement=placement,
        other_item1=None,
        other_item2=None,
    )


@pytest.fixture
def dev_session() -> Iterator[Session]:
    """Provide an isolated in-memory database session."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def seeded_session(dev_session: Session) -> Session:
    """Populate one active analysis scope with deterministic TFT fixtures."""
    rows: list[Any] = [
        ItemMetadata(
            patch="16.12",
            tft_set_number=17,
            item_api_name="TFT_Item_GuinsoosRageblade",
            item_name="TFT_Item_GuinsoosRageblade",
            item_type="artifact",
        )
    ]
    for placement in range(1, 9):
        puuid = f"p{placement}"
        rageblade = placement <= 4
        traits = "TFT17_Sniper_1"
        if rageblade:
            traits = "TFT17_DarkStar_2#TFT17_Sniper_1"
        elif placement == 5:
            traits = "TFT17_DarkStarPrime_1#TFT17_Sniper_1"
        rows.extend(
            [
                _match("m1", puuid),
                _board("m1", puuid, placement, traits=traits),
                _unit(
                    "m1",
                    puuid,
                    "TFT17_Jinx",
                    placement,
                    item1=(
                        "TFT_Item_GuinsoosRageblade" if rageblade else None
                    ),
                ),
            ]
        )
        if rageblade:
            rows.append(
                _item(
                    "m1",
                    puuid,
                    "TFT_Item_GuinsoosRageblade",
                    "TFT17_Jinx",
                    placement,
                )
            )
    rows.extend(
        [
            _match("m2", "p1", patch="16.11"),
            _board("m2", "p1", 1, traits="TFT17_DarkStar_3"),
            _unit("m2", "p1", "TFT17_Kaisa", 1),
        ]
    )
    dev_session.add_all(rows)
    dev_session.commit()
    build_match_query_table(dev_session, patch="16.12")
    build_unit_query_table(dev_session, refresh_patch=False)
    build_item_query_table(dev_session, refresh_patch=False)
    build_trait_query_table(dev_session, refresh_patch=False)
    return dev_session


def _call_tool(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    tool: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Invoke an SDK database tool against a supplied test session."""

    async def fake_run_db_tool(
        ctx: ToolContext[Any], operation: Callable[[Session], dict[str, Any]], **_: Any
    ) -> dict[str, Any]:
        """Execute the database operation synchronously in the fixture session."""
        state = AnalysisCallState(tool=ctx.tool_name, call_id=ctx.tool_call_id)
        token = set_analysis_call(state)
        try:
            return operation(session)
        finally:
            reset_analysis_call(token)

    from domain.tools.db_tools import cohort_tools, deltas, ranking_tools

    monkeypatch.setattr(db_tool_utils, "run_db_tool", fake_run_db_tool)
    monkeypatch.setattr(ranking_tools, "run_db_tool", fake_run_db_tool)
    monkeypatch.setattr(cohort_tools, "run_db_tool", fake_run_db_tool)
    monkeypatch.setattr(deltas, "run_db_tool", fake_run_db_tool)
    payload = json.dumps(kwargs)
    ctx = ToolContext(
        None,
        tool_name=tool.name,
        tool_call_id=f"test-{tool.name}",
        tool_arguments=payload,
    )
    return asyncio.run(tool.on_invoke_tool(ctx, payload))
