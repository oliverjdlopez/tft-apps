from __future__ import annotations

import json

from sqlalchemy import func, inspect, select

from db.models import (
    ANALYSIS_FACT_SCHEMA_VERSION,
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardTraitList,
    AnalysisBoardUnit,
    AnalysisBoardUnitList,
    AnalysisFactBuild,
    AnalysisScope,
    RawMatch,
)
from domain.tools.db_tools import cohort_tools, deltas, ranking_tools, utils
from domain.tools.db_tools.cohort_query import compile_filter_group
from domain.tools.db_tools.models import FilterGroup
from conftest import _call_tool


def test_rebuild_publishes_anonymous_fact_counts_and_schema(seeded_session) -> None:
    scope = seeded_session.scalar(
        select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
    )
    build = seeded_session.get(AnalysisFactBuild, scope.scope_id)

    assert build.status == "ready"
    assert build.board_count == 8
    assert build.lobby_count == 1
    assert build.unit_count == 8
    assert build.item_count == 4
    assert build.trait_count == 13
    assert seeded_session.scalar(
        select(func.count(func.distinct(AnalysisBoard.lobby_key)))
    ) == 1
    assert (
        seeded_session.scalar(select(func.count()).select_from(AnalysisBoardUnitList))
        == 8
    )
    assert (
        seeded_session.scalar(select(func.count()).select_from(AnalysisBoardTraitList))
        == 8
    )

    forbidden = {
        "match_id",
        "puuid",
        "riot_id_game_name",
        "riot_id_tagline",
        "game_datetime",
        "ingested_at",
    }
    inspector = inspect(seeded_session.bind)
    for table in (
        "analysis_boards",
        "analysis_board_unit_lists",
        "analysis_board_trait_lists",
        "analysis_board_units",
        "analysis_board_items",
        "analysis_board_traits",
    ):
        assert forbidden.isdisjoint(column["name"] for column in inspector.get_columns(table))


def test_filter_group_compiler_conjoins_conditions_and_exact_holder(
    seeded_session,
) -> None:
    """Require every structured entity condition on the same board."""
    scope = seeded_session.scalar(
        select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
    )
    group = FilterGroup.model_validate(
        {
            "unit_conditions": [
                {"name": "TFT17_Jinx", "star_level": 2},
            ],
            "item_conditions": [
                {
                    "name": "TFT_Item_GuinsoosRageblade",
                    "holder": "TFT17_Jinx",
                    "holder_star_level": 2,
                }
            ],
            "trait_conditions": [{"name": "TFT17_DarkStar", "tier": "Bronze"}],
            "level": 9,
            "min_level": 8,
            "max_level": 10,
        }
    )

    assert seeded_session.scalar(
        select(func.count())
        .select_from(AnalysisBoard)
        .where(
            AnalysisBoard.scope_id == scope.scope_id,
            compile_filter_group(group, AnalysisBoard),
        )
    ) == 4


def test_name_only_conditions_require_presence_without_other_constraints(
    seeded_session,
) -> None:
    """Interpret a name-only condition as unconstrained entity presence."""
    scope = seeded_session.scalar(
        select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
    )

    for field, name, expected_boards in (
        ("unit_conditions", "TFT17_Jinx", 8),
        ("item_conditions", "TFT_Item_GuinsoosRageblade", 4),
        ("trait_conditions", "TFT17_DarkStar", 4),
    ):
        group = FilterGroup.model_validate({field: [{"name": name}]})
        count = seeded_session.scalar(
            select(func.count())
            .select_from(AnalysisBoard)
            .where(
                AnalysisBoard.scope_id == scope.scope_id,
                compile_filter_group(group, AnalysisBoard),
            )
        )
        assert count == expected_boards


def test_rank_units_uses_scalar_item_and_trait_conditions(
    monkeypatch, seeded_session
) -> None:
    """Bind an item to ranked units and require a same-board active trait."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_units,
        item="TFT_Item_GuinsoosRageblade",
        trait="TFT17_DarkStar",
    )

    row = result["results"][0]
    assert row["unit_name"] == "TFT17_Jinx"
    assert row["games"] == 4
    assert row["universe_games"] == 4
    assert row["pick_rate"] == 1.0


def test_rank_traits_uses_scalar_unit_board_condition(
    monkeypatch, seeded_session
) -> None:
    """Rank all active traits on boards containing one exact unit."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_traits,
        unit="TFT17_Jinx",
    )

    by_name = {row["trait_name"]: row for row in result["results"]}
    assert result["context"]["population_boards"] == 8
    assert by_name["TFT17_Sniper"]["games"] == 8
    assert by_name["TFT17_DarkStar"]["games"] == 4


def test_rank_units_returns_relative_delta_for_trait_population(
    monkeypatch, seeded_session
) -> None:
    """Compare a ranked unit inside and outside its scalar trait population."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_units,
        trait="TFT17_DarkStar",
    )

    assert result["results"][0]["unit_name"] == "TFT17_Jinx"
    assert result["results"][0]["delta"] is None
    assert result["results"][0]["relative_delta"] == -4.0


def test_rank_loadouts_uses_scalar_trait_board_condition(
    monkeypatch, seeded_session
) -> None:
    """Rank item-filtered loadouts only on boards with one active trait."""
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_unit_loadouts,
        item_1="TFT_Item_GuinsoosRageblade",
        trait="TFT17_DarkStar",
    )

    assert result["context"]["population_boards"] == 4
    assert result["page"]["count"] == 1
    assert result["results"][0]["unit_name"] == "TFT17_Jinx"
    assert result["results"][0]["boards"] == 4
    assert result["results"][0]["loadout_pick_rate"] == 1.0


def test_query_cohort_groups_holder_dimensions(monkeypatch, seeded_session) -> None:
    monkeypatch.setattr(cohort_tools, "MIN_PUBLIC_BOARDS", 1)
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    result = _call_tool(
        monkeypatch,
        seeded_session,
        cohort_tools.query_cohort,
        cohort={"unit_conditions": [{"name": "TFT17_Jinx"}]},
        group_by=["unit_name", "item_name"],
        min_sample=4,
        max_sample=4,
    )

    assert result["context"]["population_boards"] == 8
    assert result["page"] == {"offset": 0, "count": 1, "has_more": False}
    assert result["results"] == [
        {
            "unit_name": "TFT17_Jinx",
            "item_name": "TFT_Item_GuinsoosRageblade",
            "distinct_boards": 4,
            "distinct_lobbies": 1,
            "avg_placement": 2.5,
            "top4_rate": 1.0,
            "win_rate": 0.25,
            "pick_rate": 0.5,
        }
    ]


def test_fact_consumers_require_ready_build_and_reactivate(
    monkeypatch, seeded_session
) -> None:
    """Reject every fact-backed query until the active build is ready."""
    monkeypatch.setattr(cohort_tools, "MIN_PUBLIC_BOARDS", 1)
    monkeypatch.setattr(utils, "MIN_PUBLIC_BOARDS", 1)
    scope = seeded_session.scalar(
        select(AnalysisScope).where(AnalysisScope.is_active.is_(True))
    )
    build = seeded_session.get(AnalysisFactBuild, scope.scope_id)
    build.status = "incomplete"
    seeded_session.commit()

    simple = _call_tool(
        monkeypatch,
        seeded_session,
        cohort_tools.compare_cohorts,
        target={"unit_conditions": [{"name": "TFT17_Jinx"}]},
        baseline={"trait_conditions": [{"name": "TFT17_DarkStar"}]},
    )
    leveled = _call_tool(
        monkeypatch,
        seeded_session,
        cohort_tools.compare_cohorts,
        target={"level": 9},
    )
    structured = _call_tool(
        monkeypatch,
        seeded_session,
        cohort_tools.compare_cohorts,
        target={"unit_conditions": [{"name": "TFT17_Jinx", "star_level": 2}]},
    )
    conditioned = _call_tool(
        monkeypatch,
        seeded_session,
        ranking_tools.rank_units,
        trait="TFT17_DarkStar",
    )
    grouped = _call_tool(
        monkeypatch,
        seeded_session,
        cohort_tools.query_cohort,
        cohort={"unit_conditions": [{"name": "TFT17_Jinx"}]},
        group_by=["unit_name"],
    )
    delta = _call_tool(
        monkeypatch,
        seeded_session,
        deltas.get_cohort_unit_deltas,
        cohort={"unit_conditions": [{"name": "TFT17_Jinx"}]},
    )

    assert "full tft-rebuild-tables" in simple["error"]["message"]
    assert "full tft-rebuild-tables" in leveled["error"]["message"]
    assert "full tft-rebuild-tables" in structured["error"]["message"]
    assert "full tft-rebuild-tables" in conditioned["error"]["message"]
    assert "full tft-rebuild-tables" in grouped["error"]["message"]
    assert "full tft-rebuild-tables" in delta["error"]["message"]

    build.status = "ready"
    seeded_session.commit()
    activated = _call_tool(
        monkeypatch,
        seeded_session,
        cohort_tools.compare_cohorts,
        target={"unit_conditions": [{"name": "TFT17_Jinx", "star_level": 2}]},
    )
    assert activated["kind"] == "comparison"


def test_fact_relationships_have_no_orphans(seeded_session) -> None:
    assert seeded_session.scalar(
        select(func.count())
        .select_from(AnalysisBoardItem)
        .outerjoin(
            AnalysisBoardUnit,
            (AnalysisBoardUnit.scope_id == AnalysisBoardItem.scope_id)
            & (AnalysisBoardUnit.board_key == AnalysisBoardItem.board_key)
            & (AnalysisBoardUnit.unit_idx == AnalysisBoardItem.unit_idx),
        )
        .where(AnalysisBoardUnit.board_key.is_(None))
    ) == 0
    assert seeded_session.scalar(
        select(func.count())
        .select_from(AnalysisBoardTrait)
        .outerjoin(
            AnalysisBoard,
            (AnalysisBoard.scope_id == AnalysisBoardTrait.scope_id)
            & (AnalysisBoard.board_key == AnalysisBoardTrait.board_key),
        )
        .where(AnalysisBoard.board_key.is_(None))
    ) == 0


def test_compare_cohorts_returns_hand_calculated_clustered_intervals(
    monkeypatch, dev_session
) -> None:
    scope = AnalysisScope(
        patch="16.12",
        queue_id=1100,
        tft_set_number=17,
        is_active=True,
        status="ready",
        universe_boards=120,
    )
    dev_session.add(scope)
    dev_session.flush()
    dev_session.add(
        AnalysisFactBuild(
            scope_id=scope.scope_id,
            schema_version=ANALYSIS_FACT_SCHEMA_VERSION,
            status="ready",
            processed_match_count=30,
            lobby_count=30,
            board_count=120,
            unit_count=120,
            item_count=0,
            trait_count=0,
        )
    )
    for lobby in range(30):
        match_id = f"m{lobby}"
        lobby_key = f"lobby-{lobby}"
        dev_session.add(
            RawMatch(
                match_id=match_id,
                region="americas",
                platform="na1",
                game_datetime=lobby,
                game_length=1800.0,
                game_version="Version 16.12.1",
                patch="16.12",
                queue_id=1100,
                tft_set_number=17,
                ingested_at=lobby,
            )
        )
        for index, (unit_name, placement) in enumerate(
            (("A", 1), ("A", 4), ("B", 5), ("B", 8))
        ):
            board_key = f"board-{lobby}-{index}"
            dev_session.add(
                AnalysisBoard(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    lobby_key=lobby_key,
                    placement=placement,
                    win=placement == 1,
                    region="americas",
                    platform="na1",
                    game_length=1800.0,
                    unit_count=1,
                    completed_item_count=0,
                )
            )
            dev_session.add(
                AnalysisBoardUnit(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    unit_idx=0,
                    unit_name=unit_name,
                    star_level=2,
                    cost=1,
                    completed_item_count=0,
                    loadout_key="[]",
                )
            )
    dev_session.commit()

    result = _call_tool(
        monkeypatch,
        dev_session,
        cohort_tools.compare_cohorts,
        target={"unit_conditions": [{"name": "A"}]},
        baseline={"unit_conditions": [{"name": "B"}]},
    )

    effects = {effect["metric"]: effect for effect in result["effects"]}
    assert effects["avg_placement"] == {
        "metric": "avg_placement",
        "estimate": -4.0,
        "cluster_robust_standard_error": 0.0,
        "confidence_interval_95": {"lower": -4.0, "upper": -4.0},
    }
    assert effects["top4_rate"]["estimate"] == 1.0
    assert effects["win_rate"]["estimate"] == 0.5
    assert "p_value" not in json.dumps(result).lower()
