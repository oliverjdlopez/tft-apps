"""Exercise ranked discovery through the ingestion collector without Riot I/O."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.chat_tft_riot import RiotAPIError
from scripts.ingestion.riot_fetch import collect_ladder_puuids


def collect(riot, tiers, max_new_matches=None):
    """Run ingestion discovery with five match histories per selected player.

    Args:
        riot: Fake client exposing the requested ladder endpoints.
        tiers: Ordered tiers to discover.
        max_new_matches: Optional cap used to derive the player target.

    Returns:
        Unique player IDs and per-tier summaries from the real collector.
    """
    return asyncio.run(collect_ladder_puuids(
        riot, platform="na1", queue="RANKED_TFT", tiers=tiers,
        max_new_matches=max_new_matches, matches_per_player=5,
    ))


@pytest.mark.parametrize("tier", [
    "iron", "bronze", "silver", "gold", "platinum", "emerald", "DIAMOND",
])
def test_lower_tiers_page_all_divisions_and_deduplicate(tier):
    """Verify uncapped discovery exhausts divisions and deduplicates players."""
    fetch = AsyncMock(side_effect=[
        [{"puuid": "a"}], [{"puuid": "a"}, {"puuid": "b"}, {}], [],
        [{"puuid": "c"}], [], [], [{"puuid": "d"}], [],
    ])
    riot = SimpleNamespace(get_tft_league_v1_entries_by_division=fetch)
    players, summaries = collect(riot, [tier])
    assert set(players) == {"a", "b", "c", "d"}
    assert summaries == [{"tier": tier, "entries": 6, "taken": 4}]
    assert [(c.kwargs["division"], c.kwargs["queries"]["page"])
            for c in fetch.call_args_list] == [
        ("I", 1), ("I", 2), ("I", 3), ("II", 1), ("II", 2),
        ("III", 1), ("IV", 1), ("IV", 2),
    ]
    assert all(c.kwargs["tier"] == tier.upper() and
               c.kwargs["region"] == "na1" and
               c.kwargs["queries"]["queue"] == "RANKED_TFT"
               for c in fetch.call_args_list)


def test_existing_target_stops_lower_tier_pagination():
    """Verify capped ingestion stops discovery once its player target is met."""
    fetch = AsyncMock(return_value=[{"puuid": "a"}, {"puuid": "b"}])
    riot = SimpleNamespace(get_tft_league_v1_entries_by_division=fetch)
    players, _ = collect(riot, ["diamond", "emerald"], max_new_matches=5)
    assert len(players) == 1
    assert fetch.call_count == 1


@pytest.mark.parametrize("tier", ["master", "grandmaster", "challenger"])
def test_mixed_tiers_preserve_apex_discovery_and_continue_after_error(tier):
    """Verify a page failure retains players and permits subsequent top tiers."""
    fetch = AsyncMock(side_effect=[
        [{"puuid": "a"}], RiotAPIError(503, "unavailable"),
    ])
    top = AsyncMock(return_value={"entries": [{"puuid": "a"}, {"puuid": "b"}]})
    riot = SimpleNamespace(get_tft_league_v1_entries_by_division=fetch, league_top=top)
    players, summaries = collect(riot, ["diamond", tier])
    assert set(players) == {"a", "b"}
    assert summaries[0]["status"] == 503
    top.assert_awaited_once_with(tier, "na1", "RANKED_TFT")


def test_invalid_tier_is_rejected_before_request():
    """Verify misspelled tiers fail explicitly during player discovery."""
    with pytest.raises(ValueError, match="Unsupported ranked tier"):
        collect(SimpleNamespace(), ["diamon"])
