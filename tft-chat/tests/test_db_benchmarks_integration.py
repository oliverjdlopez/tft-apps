"""PostgreSQL integration checks using only the isolated RDS_TEST_* target."""

from __future__ import annotations

import asyncio
import json
import os

import pytest
from agents.tool_context import ToolContext
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.config import resolve_database_target
from db.models import (
    ALL_STARS,
    ALL_TRAIT_TIERS,
    ANALYSIS_FACT_SCHEMA_VERSION,
    ITEM_OVERALL_UNIT_NAME,
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardTraitList,
    AnalysisBoardUnit,
    AnalysisBoardUnitList,
    AnalysisFactBuild,
    AnalysisScope,
    ItemStatQueryTable,
    TraitStatQueryTable,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
    SET_17_TRAIT_COLUMNS,
    SET_17_UNIT_COLUMNS,
)
from db.session import open_db
from domain.tools import call_tool
from domain.tools.db_tools import utils as db_tool_utils
from scripts.benchmarks import main as benchmark_main
from scripts.benchmarks import utils as benchmark_utils


@pytest.fixture(scope="module", autouse=True)
def _require_test_database_in_ci() -> None:
    """Fail in CI instead of allowing a broken configured test DB to skip."""
    if os.environ.get("CI", "").lower() != "true":
        return
    try:
        target = resolve_database_target("test")
        session = open_db(target)
        session.close()
    except Exception:
        pytest.fail(
            "CI RDS_TEST_* PostgreSQL target is configured but unavailable",
            pytrace=False,
        )


def _seed_ready_population(session) -> int:
    """Insert reportable anonymous facts and aggregate rows without rebuilding."""
    board_count = 256
    scope = AnalysisScope(
        patch="benchmark-fixture",
        queue_id=1100,
        tft_set_number=17,
        is_active=True,
        status="ready",
        universe_boards=board_count,
    )
    session.add(scope)
    session.flush()
    session.add(
        AnalysisFactBuild(
            scope_id=scope.scope_id,
            schema_version=ANALYSIS_FACT_SCHEMA_VERSION,
            status="ready",
            lobby_count=32,
            board_count=board_count,
            unit_count=board_count,
            item_count=board_count // 2,
            trait_count=board_count + board_count // 2,
        )
    )

    item_name = "TFT_Item_GuinsoosRageblade"
    units = ("TFT17_Jinx", "TFT17_Kaisa")
    unit_feature_columns = {name: SET_17_UNIT_COLUMNS[display] for name, display in zip(units, ("Jinx", "Kai'Sa"))}
    sniper_column = SET_17_TRAIT_COLUMNS["Sniper"]
    dark_star_column = SET_17_TRAIT_COLUMNS["Dark Star"]
    unit_placements = {name: [] for name in units}
    trait_placements = {"TFT17_Sniper": [], "TFT17_DarkStar": []}
    item_placements = {name: [] for name in units}
    loadout_placements = {name: {} for name in units}

    for lobby in range(32):
        for position in range(8):
            board_index = lobby * 8 + position
            board_key = f"benchmark-board-{board_index:03d}"
            unit_name = units[position % 2]
            placement = position + 1
            holds_item = (position // 2) % 2 == 0
            active_dark_star = position < 4
            session.add(
                AnalysisBoard(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    lobby_key=f"benchmark-lobby-{lobby:02d}",
                    placement=placement,
                    win=placement == 1,
                    level=8,
                    region="fixture",
                    platform="fixture",
                    game_length=1800.0,
                    unit_count=1,
                    completed_item_count=int(holds_item),
                )
            )
            loadout = json.dumps([item_name] if holds_item else [], separators=(",", ":"))
            loadout_placements[unit_name].setdefault(loadout, []).append(placement)
            session.add(
                AnalysisBoardUnit(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    unit_idx=0,
                    unit_name=unit_name,
                    star_level=2,
                    cost=5,
                    completed_item_count=int(holds_item),
                    loadout_key=loadout,
                    item_1=item_name if holds_item else None,
                    item_2=None,
                    item_3=None,
                )
            )
            # Item facts reference a composite unit key, so publish this
            # parent before inserting a board item through the ORM.
            session.flush()
            if holds_item:
                item_placements[unit_name].append(placement)
                session.add(
                    AnalysisBoardItem(
                        scope_id=scope.scope_id,
                        board_key=board_key,
                        unit_idx=0,
                        item_slot=0,
                        item_api_name=item_name,
                        item_name=item_name,
                    )
                )
            session.add(
                AnalysisBoardTrait(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    trait_name="TFT17_Sniper",
                    num_units=2,
                    style=1,
                    tier_current=1,
                    tier_total=4,
                )
            )
            trait_placements["TFT17_Sniper"].append(placement)
            if active_dark_star:
                session.add(
                    AnalysisBoardTrait(
                        scope_id=scope.scope_id,
                        board_key=board_key,
                        trait_name="TFT17_DarkStar",
                        num_units=2,
                        style=1,
                        tier_current=1,
                        tier_total=4,
                    )
                )
                trait_placements["TFT17_DarkStar"].append(placement)

            # The wide fact lists are the indexed feature surface used by
            # cohort filters; populate them directly as part of the fixture.
            # Flush their parent facts first because these Core inserts bypass
            # the ORM unit-of-work's automatic flush ordering.
            session.flush()
            session.execute(
                AnalysisBoardUnitList.__table__.insert().values(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    **{column: 2 if column == unit_feature_columns[unit_name] else 0 for column in SET_17_UNIT_COLUMNS.values()},
                )
            )
            session.execute(
                AnalysisBoardTraitList.__table__.insert().values(
                    scope_id=scope.scope_id,
                    board_key=board_key,
                    **{
                        column: int(
                            column == sniper_column
                            or (active_dark_star and column == dark_star_column)
                        )
                        for column in SET_17_TRAIT_COLUMNS.values()
                    },
                )
            )
            unit_placements[unit_name].append(placement)

    session.flush()
    for unit_name, placements in unit_placements.items():
        count = len(placements)
        session.add(
            UnitStatQueryTable(
                scope_id=scope.scope_id,
                unit_name=unit_name,
                star_level=ALL_STARS,
                tft_set_number=17,
                cost=5,
                games=count,
                avg_placement=sum(placements) / count,
                top4_rate=sum(place <= 4 for place in placements) / count,
                win_rate=sum(place == 1 for place in placements) / count,
                pick_rate=count / board_count,
                universe_games=board_count,
            )
        )
        held = item_placements[unit_name]
        item_count = len(held)
        session.add(
            ItemStatQueryTable(
                scope_id=scope.scope_id,
                item_name=item_name,
                unit_name=unit_name,
                item_api_name=item_name,
                item_type="completed",
                tft_set_number=17,
                holds=item_count,
                boards=item_count,
                avg_placement=sum(held) / item_count,
                top4_rate=sum(place <= 4 for place in held) / item_count,
                win_rate=sum(place == 1 for place in held) / item_count,
                pick_rate_per_board=item_count / len(placements),
                universe_games=board_count,
            )
        )
        for loadout_key, placements_for_loadout in loadout_placements[unit_name].items():
            boards = len(placements_for_loadout)
            has_item = loadout_key != "[]"
            session.add(
                UnitLoadoutStatQueryTable(
                    scope_id=scope.scope_id,
                    unit_name=unit_name,
                    star_level=ALL_STARS,
                    loadout_key=loadout_key,
                    item_count=int(has_item),
                    item_1=item_name if has_item else None,
                    item_2=None,
                    item_3=None,
                    boards=boards,
                    avg_placement=sum(placements_for_loadout) / boards,
                    top4_rate=sum(place <= 4 for place in placements_for_loadout) / boards,
                    win_rate=sum(place == 1 for place in placements_for_loadout) / boards,
                    unit_boards=count,
                    loadout_pick_rate=boards / count,
                    placement_sum=sum(placements_for_loadout),
                    outcome_count=boards,
                    top4_count=sum(place <= 4 for place in placements_for_loadout),
                    win_count=sum(place == 1 for place in placements_for_loadout),
                )
            )
    all_item_placements = [place for values in item_placements.values() for place in values]
    overall_item_count = len(all_item_placements)
    session.add(
        ItemStatQueryTable(
            scope_id=scope.scope_id,
            item_name=item_name,
            unit_name=ITEM_OVERALL_UNIT_NAME,
            item_api_name=item_name,
            item_type="completed",
            tft_set_number=17,
            holds=overall_item_count,
            boards=overall_item_count,
            avg_placement=sum(all_item_placements) / overall_item_count,
            top4_rate=sum(place <= 4 for place in all_item_placements) / overall_item_count,
            win_rate=sum(place == 1 for place in all_item_placements) / overall_item_count,
            pick_rate_per_board=overall_item_count / board_count,
            universe_games=board_count,
        )
    )
    for trait_name, placements in trait_placements.items():
        count = len(placements)
        session.add(
            TraitStatQueryTable(
                scope_id=scope.scope_id,
                trait_name=trait_name,
                tier=ALL_TRAIT_TIERS,
                tft_set_number=17,
                games=count,
                avg_placement=sum(placements) / count,
                top4_rate=sum(place <= 4 for place in placements) / count,
                win_rate=sum(place == 1 for place in placements) / count,
                pick_rate=count / board_count,
                universe_games=board_count,
            )
        )
    session.commit()
    return scope.scope_id


@pytest.mark.timeout(seconds=180)
def test_benchmark_reads_reportable_holder_and_grouped_data_from_test_target(
    conn, monkeypatch, tmp_path
) -> None:
    """Exercise benchmark workloads against seeded isolated PostgreSQL facts."""
    target = resolve_database_target("test")
    scope_id = _seed_ready_population(conn)
    original_opener = db_tool_utils.open_db
    opener_calls: list[object] = []

    def test_target_opener(*_args, **kwargs):
        """Route worker-thread tools to the isolated fixture database only."""
        assert kwargs.get("ensure_schema") is False
        opener_calls.append(scope_id)
        return open_db(target, ensure_schema=False)

    monkeypatch.setattr(benchmark_utils, "_real_open_db", test_target_opener)
    monkeypatch.setattr("db.session.database_label", lambda *_args: target.credential_safe_url)
    monkeypatch.setattr(benchmark_main, "shutdown_database_worker", lambda: None)
    args = benchmark_main.build_parser().parse_args(
        [
            "--suite",
            "all",
            "--light-runs",
            "1",
            "--heavy-runs",
            "1",
            "--concurrency",
            "2",
            "--no-profile",
            "--output-root",
            str(tmp_path / "benchmarks"),
        ]
    )

    before = conn.execute(text("SELECT COUNT(*) FROM analysis_boards")).scalar_one()
    exit_code = asyncio.run(benchmark_main.run_benchmark(args))
    after = conn.execute(text("SELECT COUNT(*) FROM analysis_boards")).scalar_one()
    assert exit_code == 0
    assert before == after == 256
    assert opener_calls
    assert db_tool_utils.open_db is original_opener

    summaries = list((tmp_path / "benchmarks").glob("*/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["status"] == "success"
    assert summary["build_metadata"]["active_scope"]["patch"] == "benchmark-fixture"
    assert summary["build_metadata"]["active_fact_build"]["board_count"] == 256
    by_name = {case["name"]: case for case in summary["cases"]}
    anchors = summary["anchors"]
    assert by_name["compare_holder_item"]["status"] == "success"
    assert by_name["query_cohort_three_way"]["group_by"] == [
        "unit_name",
        "item_name",
        "trait_name",
    ]
    holder = anchors["unit"]
    item_name = anchors["item"]
    trait_name = anchors["trait"]
    assert by_name["compare_holder_item"]["arguments"]["target"]["item_conditions"][0]["holder"] == holder
    assert holder in {
        "TFT17_Jinx",
        "TFT17_Kaisa",
    }
    with benchmark_utils.benchmark_session_scope():
        grouped = asyncio.run(
            call_tool("query_cohort", by_name["query_cohort_three_way"]["arguments"])
        )
        compared = asyncio.run(
            call_tool(
                "compare_cohorts",
                {
                    "target": {"item_conditions": [{"name": item_name, "holder": holder}]},
                    "shared": {"unit_conditions": [{"name": holder}]},
                },
            )
        )
    assert grouped["context"]["group_by"] == ["unit_name", "item_name", "trait_name"]
    assert grouped["results"]
    assert {row["unit_name"] for row in grouped["results"]} == {holder}
    assert {row["trait_name"] for row in grouped["results"]} == {trait_name}
    assert {row["item_name"] for row in grouped["results"]} == {item_name}
    assert compared["kind"] == "comparison"
    assert compared["target"]["boards"] == 64
    assert compared["baseline"]["boards"] == 64
    assert not compared["target"]["suppressed"]
    assert not compared["baseline"]["suppressed"]


def test_benchmark_database_boundary_marks_test_transaction_read_only(
    conn, monkeypatch
) -> None:
    """Prove benchmark-scoped database tools reject writes on RDS_TEST_* only."""
    target = resolve_database_target("test")

    def test_target_opener(*_args, **kwargs):
        """Route the read-only probe to the isolated test database."""
        assert kwargs.get("ensure_schema") is False
        return open_db(target, ensure_schema=False)

    monkeypatch.setattr(benchmark_utils, "_real_open_db", test_target_opener)
    context = ToolContext(
        None,
        tool_name="benchmark_read_only_probe",
        tool_call_id="benchmark-read-only-probe",
        tool_arguments="{}",
    )

    def inspect_boundary(session):
        """Read transaction mode and confirm PostgreSQL rejects a mutation."""
        mode = session.scalar(text("SHOW transaction_read_only"))
        with pytest.raises(DBAPIError) as error:
            session.execute(
                text(
                    "INSERT INTO analysis_scopes "
                    "(patch, queue_id, tft_set_number, is_active, status, universe_boards) "
                    "VALUES ('benchmark-probe', 1100, 17, false, 'pending', 0)"
                )
            )
        sqlstate = getattr(getattr(error.value, "orig", None), "sqlstate", None)
        return {"mode": mode, "write_rejected": sqlstate == "25006"}

    with benchmark_utils.benchmark_session_scope():
        result = asyncio.run(db_tool_utils.run_db_tool(context, inspect_boundary))

    assert result == {"mode": "on", "write_rejected": True}
    assert conn.execute(text("SELECT COUNT(*) FROM analysis_scopes")).scalar_one() == 0

