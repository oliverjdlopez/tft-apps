from __future__ import annotations

from copy import deepcopy

import pytest
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.orm import Session

import db.build_query_tables as analytics
from core.config import AppConfig, ChatConfig, IngestConfig
from db.models import (
    ALL_STARS,
    ALL_TRAIT_TIERS,
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTraitList,
    AnalysisBoardUnitList,
    AnalysisFactBuild,
    AnalysisProcessedMatch,
    AnalysisScope,
    Base,
    BoardTrait,
    BoardUnit,
    ITEM_OVERALL_UNIT_NAME,
    ItemMetadata,
    ItemStatQueryTable,
    PlayerBoard,
    RawMatch,
    TraitStatQueryTable,
    UnitItem,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
)


def _configured() -> AppConfig:
    return AppConfig(
        chat=ChatConfig(patch="16.10", set_number=15),
        ingest=IngestConfig(queue="RANKED_TFT"),
    )


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Session:
    monkeypatch.setattr(analytics, "load_config", _configured)
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_connection, _record):  # type: ignore[no-untyped-def]
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    db = Session(engine, expire_on_commit=False)
    db.add_all(
        [
            ItemMetadata(
                patch="16.10",
                tft_set_number=15,
                item_api_name=name,
                item_name=name,
                item_type="unknown",
            )
            for name in ("A", "B")
        ]
    )
    db.commit()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _unit(index: int, name: str, star: int, *items: str) -> BoardUnit:
    unit = BoardUnit(unit_idx=index, unit_name=name, star_level=star, cost=4)
    unit.items.extend(
        UnitItem(item_slot=slot, item_name=item)
        for slot, item in enumerate(items)
    )
    return unit


def _board(
    puuid: str,
    placement: int | None,
    units: list[BoardUnit],
    *,
    level: int | None = None,
    trait_tier: int = 0,
) -> PlayerBoard:
    board = PlayerBoard(puuid=puuid, placement=placement, level=level)
    board.units.extend(units)
    if trait_tier:
        board.trait_rows.append(
            BoardTrait(
                trait_name="Big_Trait",
                num_units=7,
                style=3,
                tier_current=trait_tier,
                tier_total=4,
            )
        )
    return board


def _match(match_id: str, game_datetime: int, boards: list[PlayerBoard]) -> RawMatch:
    match = RawMatch(
        match_id=match_id,
        region="americas",
        platform="na1",
        game_datetime=game_datetime,
        game_length=1800.0,
        game_version="Version 16.10.1",
        patch="16.10",
        queue_id=1100,
        tft_set_number=15,
        tft_set_core_name="TFTSet15",
        ingested_at=game_datetime,
    )
    match.boards.extend(boards)
    return match


def _seed(session: Session) -> None:
    session.add_all(
        [
            _match(
                "m1",
                1,
                [
                    _board(
                        "p1",
                        1,
                        [
                            _unit(0, "Carry", 2, "A", "A"),
                            _unit(1, "Carry", 1),
                            _unit(2, "Tank", 2, "B"),
                        ],
                        level=9,
                        trait_tier=3,
                    ),
                    _board(
                        "p2",
                        8,
                        [_unit(0, "Carry", 1, "A"), _unit(1, "Support", 2)],
                        level=8,
                        trait_tier=1,
                    ),
                ],
            ),
            _match(
                "m2",
                1,
                [
                    _board(
                        "p3",
                        2,
                        [_unit(0, "Carry", 2, "B"), _unit(1, "Tank", 2)],
                        level=8,
                        trait_tier=3,
                    )
                ],
            ),
        ]
    )
    session.commit()


def _aggregate_snapshot(session: Session, scope_id: int) -> dict[str, list[tuple]]:
    models = (
        UnitStatQueryTable,
        ItemStatQueryTable,
        TraitStatQueryTable,
        UnitLoadoutStatQueryTable,
    )
    result: dict[str, list[tuple]] = {}
    for model in models:
        pk = list(model.__table__.primary_key.columns)
        rows = session.scalars(
            select(model).where(model.scope_id == scope_id).order_by(*pk)
        )
        result[model.__tablename__] = [
            tuple(getattr(row, column.name) for column in model.__table__.columns)
            for row in rows
        ]
    return result


def test_full_and_incremental_are_identical_and_replays_are_noops(
    session: Session,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _seed(session)

    first = analytics.rebuild_query_tables(session, match_ids=["m1"])
    replay = analytics.rebuild_query_tables(session, match_ids=["m1"])
    second = analytics.rebuild_query_tables(session, match_ids=["m2"])

    assert first["processed_matches"] == 1
    assert replay["processed_matches"] == 0
    assert second["processed_matches"] == 1
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    incremental = _aggregate_snapshot(session, scope.scope_id)
    assert scope.universe_boards == 3
    assert session.scalar(select(func.count()).select_from(AnalysisProcessedMatch)) == 2

    with caplog.at_level("INFO", logger=analytics.__name__):
        full = analytics.rebuild_query_tables(session, batch_size=1)
    rebuilt = _aggregate_snapshot(session, scope.scope_id)

    assert full["processed_matches"] == 2
    assert rebuilt == incremental
    batch_logs = [
        record.message
        for record in caplog.records
        if record.message.startswith("analytics rebuild batch complete")
    ]
    assert len(batch_logs) == 2
    assert "batch=1 batch_matches=1 processed_matches=1" in batch_logs[0]
    assert "batch=2 batch_matches=1 processed_matches=2" in batch_logs[1]
    assert all("transaction_pending=true" in message for message in batch_logs)


def test_deferred_incremental_batches_publish_and_validate_once(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(session)
    recalculate_calls = 0
    validation_calls = 0
    original_recalculate = analytics._recalculate_published_metrics
    original_validation = analytics.fact_validation

    def counted_recalculate(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal recalculate_calls
        recalculate_calls += 1
        return original_recalculate(*args, **kwargs)

    def counted_validation(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal validation_calls
        validation_calls += 1
        return original_validation(*args, **kwargs)

    monkeypatch.setattr(analytics, "_recalculate_published_metrics", counted_recalculate)
    monkeypatch.setattr(analytics, "fact_validation", counted_validation)

    first = analytics.process_match_batch(session, ["m1"], finalize=False)
    second = analytics.process_match_batch(session, ["m2"], finalize=False)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    fact_build = session.get(AnalysisFactBuild, scope.scope_id)

    assert first["processed_matches"] == 1
    assert second["processed_matches"] == 1
    assert recalculate_calls == validation_calls == 0
    assert scope.status == "building"
    assert fact_build.status == "incomplete"

    published = analytics.finalize_query_tables(session, scope=scope)

    assert published == {"processed_matches": 2, "boards": 3}
    assert recalculate_calls == validation_calls == 1
    assert session.get(AnalysisScope, scope.scope_id).status == "ready"
    assert session.get(AnalysisFactBuild, scope.scope_id).status == "ready"


def test_catch_up_finalizes_once_after_multiple_batches(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(session)
    recalculate_calls = 0
    validation_calls = 0
    original_recalculate = analytics._recalculate_published_metrics
    original_validation = analytics.fact_validation

    def counted_recalculate(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal recalculate_calls
        recalculate_calls += 1
        return original_recalculate(*args, **kwargs)

    def counted_validation(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal validation_calls
        validation_calls += 1
        return original_validation(*args, **kwargs)

    monkeypatch.setattr(analytics, "_recalculate_published_metrics", counted_recalculate)
    monkeypatch.setattr(analytics, "fact_validation", counted_validation)

    result = analytics.catch_up_query_tables(session, batch_size=1)

    assert result == {
        "processed_matches": 2,
        "boards": 3,
        "remaining_matches": 0,
    }
    assert recalculate_calls == validation_calls == 1


def test_null_placement_counts_boards_without_distorting_outcome_rates(
    session: Session,
) -> None:
    session.add(
        _match(
            "m-null",
            1,
            [
                _board(
                    "unknown",
                    None,
                    [_unit(0, "Carry", 2, "A"), _unit(1, "Tank", 1)],
                    trait_tier=3,
                ),
                _board(
                    "known",
                    2,
                    [_unit(0, "Carry", 2, "A"), _unit(1, "Tank", 1)],
                    trait_tier=3,
                ),
            ],
        )
    )
    session.commit()

    analytics.rebuild_query_tables(session, batch_size=1)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    rows = [
        session.get(UnitStatQueryTable, (scope.scope_id, "Carry", ALL_STARS)),
        session.get(
            ItemStatQueryTable,
            (scope.scope_id, "A", ITEM_OVERALL_UNIT_NAME),
        ),
        session.get(
            TraitStatQueryTable,
            (scope.scope_id, "Big_Trait", ALL_TRAIT_TIERS),
        ),
        session.scalar(
            select(UnitLoadoutStatQueryTable).where(
                UnitLoadoutStatQueryTable.scope_id == scope.scope_id,
                UnitLoadoutStatQueryTable.unit_name == "Carry",
                UnitLoadoutStatQueryTable.star_level == ALL_STARS,
            )
        ),
    ]

    assert scope.universe_boards == 2
    assert all(row is not None for row in rows)
    for row in rows:
        assert row.outcome_count == 1
        assert row.placement_sum == 2
        assert row.avg_placement == pytest.approx(2.0)
        assert row.top4_rate == pytest.approx(1.0)
        assert row.win_rate == pytest.approx(0.0)
    assert rows[0].games == 2
    assert rows[1].boards == 2
    assert rows[2].games == 2
    assert all(row.boards == 2 for row in rows[3:])


def test_analytics_failure_keeps_raw_rows_and_catch_up_recovers(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed(session)
    original = analytics._upsert_additive

    def fail_once(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic analytics failure")

    monkeypatch.setattr(analytics, "_upsert_additive", fail_once)
    with pytest.raises(RuntimeError, match="synthetic analytics failure"):
        analytics.rebuild_query_tables(session, match_ids=["m1"])

    assert session.get(RawMatch, "m1") is not None
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    assert scope.status == "error"
    assert session.scalar(select(func.count()).select_from(AnalysisProcessedMatch)) == 0

    monkeypatch.setattr(analytics, "_upsert_additive", original)
    recovered = analytics.catch_up_query_tables(session, batch_size=1)

    assert recovered == {
        "processed_matches": 2,
        "boards": 3,
        "remaining_matches": 0,
    }
    assert session.get(AnalysisScope, scope.scope_id).status == "ready"


def test_item_outcomes_and_loadouts(session: Session) -> None:
    _seed(session)
    analytics.rebuild_query_tables(session)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))

    item = session.get(
        ItemStatQueryTable,
        (scope.scope_id, "A", ITEM_OVERALL_UNIT_NAME),
    )
    assert item.holds == 3
    assert item.boards == 2
    assert item.placement_sum == 9
    assert item.avg_placement == pytest.approx(4.5)
    assert item.top4_rate == pytest.approx(0.5)
    assert (item.item_api_name, item.item_type) == ("A", "unknown")

    duplicate_loadout = session.scalar(
        select(UnitLoadoutStatQueryTable).where(
            UnitLoadoutStatQueryTable.scope_id == scope.scope_id,
            UnitLoadoutStatQueryTable.unit_name == "Carry",
            UnitLoadoutStatQueryTable.star_level == 2,
            UnitLoadoutStatQueryTable.item_count == 2,
        )
    )
    assert duplicate_loadout.item_1 == duplicate_loadout.item_2 == "A"
    assert duplicate_loadout.loadout_key == '["A","A"]'

def test_rebuild_materializes_wide_unit_and_trait_lists(session: Session) -> None:
    """Store max unit stars and active trait tiers at one row per board."""
    board = _board(
        "wide-features",
        1,
        [
            _unit(0, "Aatrox", 1),
            _unit(1, "Aatrox", 2),
            _unit(2, "Akali", 1),
        ],
    )
    board.trait_rows.extend(
        [
            BoardTrait(
                trait_name="Dark Star",
                num_units=4,
                style=2,
                tier_current=2,
                tier_total=4,
            ),
            BoardTrait(
                trait_name="Anima",
                num_units=1,
                style=0,
                tier_current=0,
                tier_total=4,
            ),
        ]
    )
    session.add(_match("wide", 1, [board]))
    session.commit()

    result = analytics.rebuild_query_tables(session)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    board_key = analytics.anonymous_board_key(
        scope.scope_id, "wide", "wide-features"
    )
    unit_list = session.get(
        AnalysisBoardUnitList,
        (scope.scope_id, board_key),
    )
    trait_list = session.get(
        AnalysisBoardTraitList,
        (scope.scope_id, board_key),
    )
    analysis_board = session.get(AnalysisBoard, (scope.scope_id, board_key))

    assert result["analysis_board_unit_lists"] == 1
    assert result["analysis_board_trait_lists"] == 1
    assert (unit_list.aatrox, unit_list.akali, unit_list.zoe) == (2, 1, 0)
    assert (trait_list.dark_star, trait_list.anima, trait_list.voyager) == (2, 0, 0)
    assert analysis_board.units is unit_list
    assert analysis_board.traits is trait_list
    assert unit_list.board is analysis_board
    assert trait_list.board is analysis_board


def test_cascades_and_raw_mutations_mark_processed_scope_dirty(session: Session) -> None:
    _seed(session)
    analytics.rebuild_query_tables(session)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    board = session.get(PlayerBoard, ("m1", "p1"))
    board.level = 10
    session.commit()

    assert session.get(AnalysisScope, scope.scope_id).status == "dirty"
    with pytest.raises(RuntimeError, match="requires a full rebuild"):
        analytics.rebuild_query_tables(session, match_ids=["m1"])

    analytics.rebuild_query_tables(session)
    raw = session.get(RawMatch, "m2")
    session.delete(raw)
    session.commit()

    assert session.get(PlayerBoard, ("m2", "p3")) is None
    assert session.scalar(
        select(func.count()).select_from(BoardUnit).where(BoardUnit.match_id == "m2")
    ) == 0
    assert session.get(AnalysisScope, scope.scope_id).status == "dirty"


def test_expected_normalized_foreign_keys_and_primary_keys(session: Session) -> None:
    inspector = inspect(session.bind)
    assert inspector.get_pk_constraint("raw_matches")["constrained_columns"] == [
        "match_id"
    ]
    assert inspector.get_pk_constraint("board_units")["constrained_columns"] == [
        "match_id",
        "puuid",
        "unit_idx",
    ]
    assert inspector.get_pk_constraint("unit_items")["constrained_columns"] == [
        "match_id",
        "puuid",
        "unit_idx",
        "item_slot",
    ]
    assert len(inspector.get_foreign_keys("analysis_processed_matches")) == 2
    assert all(
        foreign_key["options"].get("ondelete") == "CASCADE"
        for table in ("player_boards", "board_units", "unit_items", "board_traits")
        for foreign_key in inspector.get_foreign_keys(table)
    )


def test_fact_validation_detects_aggregate_item_type_drift(session: Session) -> None:
    """Reject aggregates whose copied family no longer matches metadata."""
    _seed(session)
    analytics.rebuild_query_tables(session)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    metadata = session.get(ItemMetadata, ("16.10", 15, "A"))
    metadata.item_type = "artifact"
    session.commit()

    result = analytics.fact_validation(session, scope, require_ready=False)

    assert result["ready"] is False
    assert result["item_metadata"]["aggregate_mismatched"] > 0


def test_rebuild_requires_persisted_item_metadata(session: Session) -> None:
    """Do not infer a canonical classification during an analytics rebuild."""
    session.delete(session.get(ItemMetadata, ("16.10", 15, "A")))
    session.add(
        _match(
            "m1",
            1,
            [_board("p1", 1, [_unit(0, "Carry", 2, "A")])],
        )
    )
    session.commit()

    with pytest.raises(RuntimeError, match="Missing item metadata"):
        analytics.rebuild_query_tables(session)


@pytest.mark.parametrize('batch_size', [1, 500])
@pytest.mark.parametrize('second_type', ['artifact', 'support'])
def test_rebuild_skips_ambiguous_rankings_and_preserves_item_facts(
    session: Session,
    caplog: pytest.LogCaptureFixture,
    batch_size: int,
    second_type: str,
) -> None:
    """Publish valid analytics despite aliases, retaining exact source cardinality."""
    unit_a = BoardUnit(unit_idx=0, unit_name="Carry", star_level=2, cost=4)
    unit_a.items.append(
        UnitItem(item_slot=0, item_api_name="API_A", item_name="Shared")
    )
    unit_b = BoardUnit(unit_idx=0, unit_name="Carry", star_level=2, cost=4)
    unit_b.items.append(
        UnitItem(item_slot=0, item_api_name="API_B", item_name="Shared")
    )
    session.add_all(
        [
            _match("m1", 1, [_board("p1", 1, [unit_a])]),
            _match("m2", 2, [_board("p2", 2, [unit_b])]),
            ItemMetadata(
                patch="16.10",
                tft_set_number=15,
                item_api_name="API_A",
                item_name="Shared",
                item_type="artifact",
            ),
            ItemMetadata(
                patch="16.10",
                tft_set_number=15,
                item_api_name="API_B",
                item_name="Shared",
                item_type=second_type,
            ),
            _match("m3", 3, [_board("p3", 3, [_unit(0, "Tank", 2, "B")])]),
        ]
    )
    session.commit()

    result = analytics.rebuild_query_tables(session, batch_size=batch_size)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    assert result['processed_matches'] == 3
    assert analytics.fact_validation(session, scope, require_ready=True)['ready'] is True
    assert session.scalar(select(func.count()).select_from(UnitItem)) == 3
    assert session.scalar(select(func.count()).select_from(AnalysisBoardItem)) == 3
    assert set(session.scalars(select(AnalysisBoardItem.item_api_name))) == {'API_A', 'API_B', 'B'}
    assert set(session.scalars(select(ItemStatQueryTable.item_name))) == {'B'}
    assert set(session.scalars(select(UnitStatQueryTable.unit_name))) == {'Carry', 'Tank'}
    assert 'Skipping item rankings' in caplog.text
    assert 'Shared' in caplog.text
    before = _aggregate_snapshot(session, scope.scope_id)
    assert analytics.rebuild_query_tables(session, match_ids=['m1', 'm2', 'm3'])['processed_matches'] == 0
    assert _aggregate_snapshot(session, scope.scope_id) == before


def test_new_item_alias_removes_prior_rankings_during_catch_up(session: Session) -> None:
    """Exclude both identities when an alias arrives after the first batch was built."""
    session.add(_match('m1', 1, [_board('p1', 1, [_unit(0, 'Carry', 2, 'A')])]))
    session.commit()
    analytics.rebuild_query_tables(session)
    assert 'A' in set(session.scalars(select(ItemStatQueryTable.item_name)))

    unit = BoardUnit(unit_idx=0, unit_name='Carry', star_level=2, cost=4)
    unit.items.append(UnitItem(item_slot=0, item_api_name='Alias_A', item_name='A'))
    session.add_all([
        ItemMetadata(patch='16.10', tft_set_number=15, item_api_name='Alias_A',
                     item_name='A', item_type='unknown'),
        _match('m2', 2, [_board('p2', 2, [unit])]),
    ])
    session.commit()
    result = analytics.catch_up_query_tables(session, batch_size=1)
    scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
    assert result['processed_matches'] == 1
    assert session.scalar(select(func.count()).select_from(ItemStatQueryTable)) == 0
    assert session.scalar(select(func.count()).select_from(AnalysisBoardItem)) == 2
    assert analytics.fact_validation(session, scope, require_ready=True)['ready'] is True
    incremental = _aggregate_snapshot(session, scope.scope_id)
    analytics.rebuild_query_tables(session, batch_size=1)
    assert _aggregate_snapshot(session, scope.scope_id) == incremental
