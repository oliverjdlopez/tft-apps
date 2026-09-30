from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from db.build_query_tables import (
    _match_set_universe_statement,
    build_item_query_table,
    build_trait_query_table,
    build_unit_query_table,
)
from db.models import (
    ALL_STARS,
    ALL_TRAIT_TIERS,
    AllMatch,
    Base,
    ITEM_OVERALL_UNIT_NAME,
    ItemMetadata,
    ItemStatQueryTable,
    PlayerBoard,
    PlayerItem,
    PlayerUnit,
    TraitStatQueryTable,
    UnitStatQueryTable,
)


def _seed(session: Session) -> None:
    common = {
        "region": "americas",
        "platform": "na1",
        "game_datetime": 1717200000000,
        "game_length": 1800.0,
        "game_version": "Version 16.11.123",
        "patch": "16.11",
        "queue_id": 1100,
        "tft_set_number": 15,
        "tft_set_core_name": "TFTSet15",
        "ingested_at": 1717200100,
    }
    session.add_all(
        [
            ItemMetadata(
                patch="16.11",
                tft_set_number=15,
                item_api_name="Sword",
                item_name="Sword",
                item_type="unknown",
            ),
            AllMatch(match_id="NA1_1", puuid="p1", **common),
            AllMatch(match_id="NA1_1", puuid="p2", **common),
            PlayerBoard(
                match_id="NA1_1",
                puuid="p1",
                comp_name=None,
                comp_code="Carry#Tank",
                star_levels="22",
                traits="Big Trait_4",
                placement=1,
            ),
            PlayerBoard(
                match_id="NA1_1",
                puuid="p2",
                comp_name=None,
                comp_code="Carry",
                star_levels="1",
                traits="Big Trait_2",
                placement=8,
            ),
            # p1 fields two copies of Carry (1* and 2*) plus a Tank; p2 fields
            # one Carry. Placements: p1 won, p2 came 8th.
            PlayerUnit(
                match_id="NA1_1",
                puuid="p1",
                unit_name="Carry",
                unit_idx=0,
                star_level=1,
                item1=None,
                item2=None,
                item3=None,
                placement=1,
                cost=4,
            ),
            PlayerUnit(
                match_id="NA1_1",
                puuid="p1",
                unit_name="Carry",
                unit_idx=1,
                star_level=2,
                item1="Sword",
                item2=None,
                item3=None,
                placement=1,
                cost=4,
            ),
            PlayerUnit(
                match_id="NA1_1",
                puuid="p1",
                unit_name="Tank",
                unit_idx=2,
                star_level=2,
                item1=None,
                item2=None,
                item3=None,
                placement=1,
                cost=2,
            ),
            PlayerUnit(
                match_id="NA1_1",
                puuid="p2",
                unit_name="Carry",
                unit_idx=0,
                star_level=1,
                item1="Sword",
                item2=None,
                item3=None,
                placement=8,
                cost=4,
            ),
            # Three Sword instances across two boards, all held by Carry.
            PlayerItem(
                match_id="NA1_1",
                puuid="p1",
                item_name="Sword",
                unit_name="Carry",
                idx=0,
                placement=1,
                other_item1=None,
                other_item2=None,
            ),
            PlayerItem(
                match_id="NA1_1",
                puuid="p1",
                item_name="Sword",
                unit_name="Carry",
                idx=1,
                placement=1,
                other_item1=None,
                other_item2=None,
            ),
            PlayerItem(
                match_id="NA1_1",
                puuid="p2",
                item_name="Sword",
                unit_name="Carry",
                idx=0,
                placement=8,
                other_item1=None,
                other_item2=None,
            ),
        ]
    )
    session.commit()


@pytest.fixture
def session():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        _seed(db)
        yield db
    engine.dispose()


def test_build_unit_query_table(session: Session) -> None:
    # Per-star rows: (Carry, 1*) x2 boards, (Carry, 2*), (Tank, 2*);
    # ALL_STARS rollups: Carry, Tank.
    assert build_unit_query_table(session) == 5

    carry = (
        session.query(UnitStatQueryTable)
        .filter_by(unit_name="Carry", star_level=ALL_STARS)
        .one()
    )
    assert carry.games == 2  # two copies on p1's board collapse to one
    assert carry.avg_placement == pytest.approx(4.5)
    assert carry.top4_rate == pytest.approx(0.5)
    assert carry.win_rate == pytest.approx(0.5)
    assert carry.pick_rate == pytest.approx(1.0)
    assert carry.universe_games == 2

    two_star = (
        session.query(UnitStatQueryTable).filter_by(unit_name="Carry", star_level=2).one()
    )
    assert two_star.games == 1

    tank = (
        session.query(UnitStatQueryTable)
        .filter_by(unit_name="Tank", star_level=ALL_STARS)
        .one()
    )
    assert tank.games == 1
    assert tank.pick_rate == pytest.approx(0.5)


def test_build_item_query_table(session: Session) -> None:
    # One per-holder row (Sword on Carry) plus the unit_name=NULL rollup.
    assert build_item_query_table(session) == 2

    overall = (
        session.query(ItemStatQueryTable)
        .filter_by(item_name="Sword")
        .filter(ItemStatQueryTable.unit_name == ITEM_OVERALL_UNIT_NAME)
        .one()
    )
    assert overall.holds == 3  # two instances on p1's board plus one on p2's
    assert overall.boards == 2
    # Outcome metrics are board-weighted even though holds remains instance-weighted.
    assert overall.avg_placement == pytest.approx(4.5)
    assert overall.top4_rate == pytest.approx(0.5)
    assert overall.win_rate == pytest.approx(0.5)
    assert overall.pick_rate_per_board == pytest.approx(1.0)
    assert overall.universe_games == 2

    holder = (
        session.query(ItemStatQueryTable)
        .filter_by(item_name="Sword", unit_name="Carry")
        .one()
    )
    assert holder.holds == 3
    assert holder.boards == 2


def test_build_trait_query_table(session: Session) -> None:
    assert build_trait_query_table(session) == 3

    overall = (
        session.query(TraitStatQueryTable)
        .filter_by(trait_name="Big Trait", tier=ALL_TRAIT_TIERS)
        .one()
    )
    assert overall.games == 2
    assert overall.avg_placement == pytest.approx(4.5)
    assert overall.top4_rate == pytest.approx(0.5)
    assert overall.win_rate == pytest.approx(0.5)
    assert overall.pick_rate == pytest.approx(1.0)
    assert overall.universe_games == 2

    tiers = {
        row.tier: row
        for row in session.query(TraitStatQueryTable)
        .filter(
            TraitStatQueryTable.trait_name == "Big Trait",
            TraitStatQueryTable.tier != ALL_TRAIT_TIERS,
        )
        .all()
    }
    assert set(tiers) == {2, 4}
    assert tiers[4].avg_placement == pytest.approx(1.0)
    assert tiers[2].avg_placement == pytest.approx(8.0)


def test_trait_universe_query_reuses_postgres_fallback_parameter() -> None:
    compiled = _match_set_universe_statement().compile(dialect=postgresql.dialect())

    assert len(compiled.params) == 1


def test_build_trait_query_table_creates_missing_table(session: Session) -> None:
    TraitStatQueryTable.__table__.drop(session.bind)

    assert build_trait_query_table(session) == 3
    assert inspect(session.bind).has_table("trait_stats")


def test_query_tables_have_database_primary_keys(session: Session) -> None:
    build_unit_query_table(session)
    build_item_query_table(session)
    build_trait_query_table(session)

    inspector = inspect(session.bind)
    assert inspector.get_pk_constraint("unit_stats")["constrained_columns"] == [
        "scope_id",
        "unit_name",
        "star_level",
    ]
    assert inspector.get_pk_constraint("item_stats")["constrained_columns"] == [
        "scope_id",
        "item_name",
        "unit_name",
    ]
    assert inspector.get_pk_constraint("trait_stats")["constrained_columns"] == [
        "scope_id",
        "trait_name",
        "tier",
    ]
