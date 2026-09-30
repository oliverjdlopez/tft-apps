from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

import db.build_query_tables as query_tables
from core.config import AppConfig, ChatConfig, IngestConfig
from db.build_query_tables import build_match_query_table, build_unit_query_table
from db.models import (
    AllMatch,
    AnalysisScope,
    Base,
    Match,
    PlayerBoard,
    PlayerUnit,
    RawMatch,
    UnitStatQueryTable,
)
from db.session import _ensure_model_indexes


@pytest.fixture
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def test_build_unit_query_table_normalizes_legacy_columns(session) -> None:
    common = {
        "region": "americas",
        "platform": "na1",
        "game_datetime": 1,
        "game_length": 1800.0,
        "game_version": "Version 16.10.1",
        "patch": "16.10",
        "queue_id": 1100,
        "tft_set_number": 15,
        "tft_set_core_name": "TFTSet15",
        "ingested_at": 1,
    }
    session.add(AllMatch(match_id="m1", puuid="p1", **common))
    session.add(PlayerBoard(match_id="m1", puuid="p1", placement=1))
    session.add(
        PlayerUnit(
            match_id="m1",
            puuid="p1",
            unit_name="Ashe",
            unit_idx=0,
            star_level=2,
            placement=1,
            cost=5,
        )
    )
    session.commit()
    session.execute(text("ALTER TABLE player_units RENAME COLUMN unit_name TO name"))
    session.execute(text("ALTER TABLE player_units RENAME COLUMN cost TO rarity"))
    session.execute(text("UPDATE player_units SET rarity = rarity - 1"))
    session.execute(text("ALTER TABLE unit_stats RENAME COLUMN unit_name TO name"))
    session.commit()

    assert build_unit_query_table(session) == 2

    columns_by_table = {
        table: {column["name"] for column in inspect(session.bind).get_columns(table)}
        for table in ("player_units", "unit_stats")
    }
    rows = session.query(UnitStatQueryTable).order_by(UnitStatQueryTable.star_level).all()
    assert "unit_name" in columns_by_table["player_units"]
    assert "name" not in columns_by_table["player_units"]
    assert "cost" in columns_by_table["player_units"]
    assert "rarity" not in columns_by_table["player_units"]
    assert "unit_name" in columns_by_table["unit_stats"]
    assert "name" not in columns_by_table["unit_stats"]
    assert [(row.unit_name, row.star_level, row.games) for row in rows] == [
        ("Ashe", 0, 1),
        ("Ashe", 2, 1),
    ]
    assert {row.cost for row in rows} == {5}


def test_build_match_query_table_uses_configured_queue(monkeypatch, session) -> None:
    common = {
        "region": "americas",
        "platform": "na1",
        "game_datetime": 1,
        "game_length": 1800.0,
        "game_version": "Version 16.10.1",
        "patch": "16.10",
        "tft_set_number": 15,
        "tft_set_core_name": "TFTSet15",
        "ingested_at": 1,
    }
    session.add_all(
        [
            AllMatch(match_id="ranked", puuid="p1", queue_id=1100, **common),
            AllMatch(match_id="normal", puuid="p2", queue_id=1090, **common),
            AllMatch(
                match_id="ranked_newer",
                puuid="p3",
                queue_id=1100,
                **{**common, "patch": "16.11", "game_version": "Version 16.11.1"},
            ),
        ]
    )
    session.commit()
    monkeypatch.setattr(
        query_tables,
        "load_config",
        lambda: AppConfig(ingest=IngestConfig(queue="1090")),
    )

    assert build_match_query_table(session) == 1

    row = session.query(Match).one()
    columns = {column["name"] for column in inspect(session.bind).get_columns("matches")}
    assert row.match_id == "normal"
    assert "patch" not in columns
    assert "queue_id" not in columns


def test_build_match_query_table_uses_configured_patch(monkeypatch, session) -> None:
    common = {
        "region": "americas",
        "platform": "na1",
        "game_datetime": 1,
        "game_length": 1800.0,
        "game_version": "Version 16.10.1",
        "patch": "16.10",
        "queue_id": 1100,
        "tft_set_number": 15,
        "tft_set_core_name": "TFTSet15",
        "ingested_at": 1,
    }
    session.add_all(
        [
            AllMatch(match_id="older", puuid="p1", **common),
            AllMatch(
                match_id="newer",
                puuid="p2",
                **{**common, "patch": "16.11", "game_version": "Version 16.11.1"},
            ),
        ]
    )
    session.commit()
    monkeypatch.setattr(
        query_tables,
        "load_config",
        lambda: AppConfig(
            chat=ChatConfig(patch="16.10.1"),
            ingest=IngestConfig(queue="RANKED_TFT"),
        ),
    )

    assert build_match_query_table(session) == 1
    assert session.query(Match).one().match_id == "older"


def test_raw_matches_has_rebuild_filter_index(session) -> None:
    indexes = {
        index["name"]: index["column_names"]
        for index in inspect(session.bind).get_indexes("all_matches")
    }

    assert indexes["ix_all_matches_queue_patch"] == ["queue_id", "patch"]


def test_schema_setup_creates_missing_model_indexes() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("DROP INDEX ix_all_matches_queue_patch"))

        assert "ix_all_matches_queue_patch" not in {
            index["name"] for index in inspect(engine).get_indexes("all_matches")
        }

        _ensure_model_indexes(engine)

        indexes = {
            index["name"]: index["column_names"]
            for index in inspect(engine).get_indexes("all_matches")
        }
        assert indexes["ix_all_matches_queue_patch"] == ["queue_id", "patch"]
    finally:
        engine.dispose()


def test_resolve_analysis_scope_without_legacy_all_matches(
    monkeypatch, session
) -> None:
    session.execute(text("DROP TABLE all_matches"))
    session.add(
        RawMatch(
            match_id="m1",
            region="americas",
            platform="na1",
            game_datetime=1,
            game_length=1800.0,
            game_version="Version 16.10.1",
            patch="16.10",
            queue_id=1100,
            tft_set_number=15,
            tft_set_core_name="TFTSet15",
            ingested_at=1,
        )
    )
    session.commit()
    monkeypatch.setattr(
        query_tables,
        "load_config",
        lambda: AppConfig(
            chat=ChatConfig(patch="16.10", set_number=15),
            ingest=IngestConfig(queue="RANKED_TFT"),
        ),
    )

    scope = query_tables.resolve_analysis_scope(session)

    assert isinstance(scope, AnalysisScope)
    assert scope.patch == "16.10"
    assert scope.queue_id == 1100
    assert scope.tft_set_number == 15


def test_represented_sets_query_reuses_postgres_coalesce_parameter() -> None:
    compiled = query_tables._represented_sets_statement("16.14", 1100).compile(
        dialect=postgresql.dialect()
    )

    assert len(
        [name for name in compiled.params if name.startswith("coalesce_")]
    ) == 1
