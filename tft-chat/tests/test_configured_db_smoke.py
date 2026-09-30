"""Opt-in read-only smoke tests for the configured application database."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import pytest

from domain.tools import call_tool


SMOKE_ENV_VAR = "CHAT_TFT_RUN_CONFIGURED_DB_SMOKE_TESTS"
MIN_PUBLIC_BOARDS = 50
logger = logging.getLogger(__name__)


def configured_db_smoke_enabled() -> bool:
    """Return whether the operator explicitly enabled live database smoke tests.

    Returns:
        True only when the dedicated opt-in variable is set to ``1``.
    """
    return os.environ.get(SMOKE_ENV_VAR, "").strip() == "1"


pytestmark = pytest.mark.skipif(
    not configured_db_smoke_enabled(),
    reason=f"set {SMOKE_ENV_VAR}=1 to test the configured app database",
)


def invoke_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Invoke a registered tool through its production database boundary.

    Args:
        name: Registered tool name.
        arguments: JSON-compatible tool arguments.

    Returns:
        JSON-compatible tool result.
    """
    logger.info("configured database smoke call started: tool=%s", name)
    started_at = time.perf_counter()
    result = asyncio.run(call_tool(name, arguments))
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 1)
    assert isinstance(result, dict), f"{name} returned {type(result).__name__}"
    assert result.get("kind") != "error", f"{name} failed: {result.get('error')}"
    logger.info(
        "configured database smoke call completed: tool=%s elapsed_ms=%s "
        "kind=%s page=%s",
        name,
        elapsed_ms,
        result.get("kind"),
        result.get("page"),
    )
    return result


@pytest.mark.parametrize(
    ("tool_name", "identity_field", "sample_field", "pick_rate_field"),
    [
        ("rank_units", "unit_name", "games", "pick_rate"),
        ("rank_items", "item_name", "boards", "pick_rate_per_board"),
        ("rank_traits", "trait_name", "games", "pick_rate"),
    ],
)
def test_configured_rankings_return_public_metric_rows(
    tool_name: str,
    identity_field: str,
    sample_field: str,
    pick_rate_field: str,
) -> None:
    """Check live ranking calls return bounded, reportable metric rows.

    Args:
        tool_name: Ranking tool under test.
        identity_field: Canonical entity-name field expected in each row.
        sample_field: Tool-specific public sample-size field.
        pick_rate_field: Tool-specific pick-rate field.
    """
    result = invoke_tool(tool_name, {"range": [0, 5]})

    assert result["page"]["offset"] == 0
    assert isinstance(result["page"]["has_more"], bool)
    assert result["page"]["count"] == len(result["results"])
    assert 1 <= result["page"]["count"] <= 5
    logger.info(
        "configured ranking verified: tool=%s entities=%s",
        tool_name,
        [row[identity_field] for row in result["results"]],
    )

    for row in result["results"]:
        assert isinstance(row[identity_field], str) and row[identity_field]
        assert row[sample_field] >= MIN_PUBLIC_BOARDS
        assert 1.0 <= row["avg_placement"] <= 8.0
        assert 0.0 <= row["top4_rate"] <= 1.0
        assert 0.0 <= row["win_rate"] <= 1.0
        assert 0.0 <= row[pick_rate_field] <= 1.0


def test_configured_name_resolution_round_trips_a_ranked_unit() -> None:
    """Resolve a canonical unit returned by the configured active scope."""
    ranking = invoke_tool("rank_units", {"range": [0, 1]})
    assert ranking["page"]["count"] == 1
    unit_name = ranking["results"][0]["unit_name"]

    resolution = invoke_tool("resolve_tft_names", {"names": [unit_name]})
    assert len(resolution["results"]) == 1
    entry = resolution["results"][0]
    assert entry["query"] == unit_name
    assert entry["resolved"] is True
    assert any(
        match["kind"] == "unit" and match["name"] == unit_name
        for match in entry["matches"]
    )
    logger.info("configured name resolution verified: unit=%s", unit_name)
