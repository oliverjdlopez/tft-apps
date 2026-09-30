from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

import db.build_query_tables as analytics
import scripts.migrate_relational_v2 as migration
from core.config import AppConfig, ChatConfig, IngestConfig
from db.models import (
    AllMatch,
    AnalysisScope,
    Base,
    BoardTrait,
    BoardUnit,
    LegacyPlayerBoard,
    LegacyPlayerItem,
    LegacyPlayerUnit,
    ItemMetadata,
    Match,
    PlayerBoard,
    RawMatch,
    UnitItem,
)
from scripts.migrate_relational_v2 import (
    MigrationConflictError,
    _legacy_unit_cost,
    migrate_relational_v2,
    migration_preflight,
    parse_legacy_traits,
)


def test_legacy_unit_cost_prefers_static_cost_over_invalid_source_value() -> None:
    """Use exact-patch static cost when legacy rarity produced an impossible value."""

    class Resolver:
        def unit_cost(self, unit_name: str) -> int | None:
            return 5 if unit_name == "TFT15_Blitzcrank" else None

    assert (
        _legacy_unit_cost(
            unit_name="TFT15_Blitzcrank",
            source_cost=7,
            rarity=6,
            patch="16.10",
            set_number=15,
            resolver_factory=lambda _patch, _set: Resolver(),
        )
        == 5
    )


def _create_legacy(engine) -> None:  # type: ignore[no-untyped-def]
    for table in (
        AllMatch.__table__,
        LegacyPlayerBoard.__table__,
        LegacyPlayerUnit.__table__,
        LegacyPlayerItem.__table__,
    ):
        table.create(engine)


def _create_normalized_v1(engine) -> None:  # type: ignore[no-untyped-def]
    statements = (
        """
        CREATE TABLE matches (
            match_id TEXT PRIMARY KEY,
            region TEXT NOT NULL,
            platform TEXT,
            game_datetime BIGINT NOT NULL,
            game_length FLOAT NOT NULL,
            game_version TEXT NOT NULL,
            patch TEXT,
            queue_id INTEGER NOT NULL,
            tft_set_number INTEGER,
            tft_set_core_name TEXT,
            ingested_at BIGINT NOT NULL
        )
        """,
        """
        CREATE TABLE participants (
            match_id TEXT NOT NULL,
            puuid TEXT NOT NULL,
            placement INTEGER NOT NULL,
            level INTEGER NOT NULL,
            last_round INTEGER NOT NULL,
            players_eliminated INTEGER NOT NULL,
            total_damage_to_players INTEGER NOT NULL,
            gold_left INTEGER NOT NULL,
            PRIMARY KEY (match_id, puuid)
        )
        """,
        """
        CREATE TABLE participant_units (
            match_id TEXT NOT NULL,
            puuid TEXT NOT NULL,
            unit_index INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            tier INTEGER NOT NULL,
            rarity INTEGER NOT NULL,
            PRIMARY KEY (
                match_id, puuid, character_id, tier, rarity, unit_index
            )
        )
        """,
        """
        CREATE TABLE participant_unit_items (
            match_id TEXT NOT NULL,
            puuid TEXT NOT NULL,
            unit_index INTEGER NOT NULL,
            item_index INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            item_name TEXT NOT NULL,
            PRIMARY KEY (
                match_id, puuid, character_id, item_name, unit_index, item_index
            )
        )
        """,
        """
        CREATE TABLE participant_traits (
            match_id TEXT NOT NULL,
            puuid TEXT NOT NULL,
            trait_name TEXT NOT NULL,
            num_units INTEGER NOT NULL,
            style INTEGER NOT NULL,
            tier_current INTEGER NOT NULL,
            tier_total INTEGER NOT NULL,
            PRIMARY KEY (match_id, puuid, trait_name)
        )
        """,
        # This derived-v1 table collides by name with the relational-v2 raw
        # unit table and therefore must be retained before v2 schema creation.
        """
        CREATE TABLE board_units (
            match_id TEXT NOT NULL,
            puuid TEXT NOT NULL,
            unit_index INTEGER NOT NULL,
            character_id TEXT NOT NULL,
            PRIMARY KEY (match_id, puuid, unit_index)
        )
        """,
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _config() -> AppConfig:
    return AppConfig(
        chat=ChatConfig(patch="16.10", set_number=15),
        ingest=IngestConfig(queue="RANKED_TFT"),
    )


def test_trait_parser_uses_final_underscore() -> None:
    parsed, malformed = parse_legacy_traits(
        "Trait_With_Underscores_3#Other_1#bad_segment"
    )
    assert parsed == [("Trait_With_Underscores", 3), ("Other", 1)]
    assert malformed == ["bad_segment"]


def test_migration_supports_normalized_v1_source_and_name_collisions() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_normalized_v1(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO matches VALUES "
                "('m1', 'americas', 'na1', 1, 1800.0, 'Version 16.10.1', "
                "'16.10', 1100, 15, 'TFTSet15', 123)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO participants VALUES "
                "('m1', 'p1', 1, 9, 40, 2, 120, 10)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO participant_units VALUES "
                "('m1', 'p1', 0, 'Carry', 2, 3), "
                "('m1', 'p1', 0, 'Tank', 1, 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO participant_unit_items VALUES "
                "('m1', 'p1', 0, 0, 'Carry', 'ItemA'), "
                "('m1', 'p1', 0, 0, 'Carry', 'ItemB'), "
                "('m1', 'p1', 0, 4, 'Carry', 'ItemC'), "
                "('m1', 'p1', 0, 5, 'Carry', 'ItemD'), "
                "('m1', 'p1', 0, 0, 'Tank', 'TankItem')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO participant_traits VALUES "
                "('m1', 'p1', 'TraitA', 4, 2, 1, 3)"
            )
        )

    with Session(engine, expire_on_commit=False) as session:
        preflight = migration_preflight(session)
        assert preflight["source_kind"] == "normalized_v1"
        assert preflight["matches"] == 1
        assert preflight["participants"] == 1
        assert preflight["duplicate_unit_index_keys"] == 1
        assert preflight["duplicate_item_slot_keys"] == 1
        assert preflight["invalid_item_slots"] == 2
        assert (
            preflight["item_representations"][
                "excess_rows_over_three_per_unit_capacity"
            ]
            == 1
        )
        assert preflight["nondeterministic_conflicts"] == 0

        result = migrate_relational_v2(
            session,
            batch_size=1,
            build_analytics=False,
        )

        raw = session.get(RawMatch, "m1")
        board = session.get(PlayerBoard, ("m1", "p1"))
        unit = session.get(BoardUnit, ("m1", "p1", 0))
        item = session.get(UnitItem, ("m1", "p1", 0, 0))
        trait = session.get(BoardTrait, ("m1", "p1", "TraitA"))
        assert raw is not None
        assert board is not None
        assert (board.placement, board.level, board.win) == (1, 9, True)
        assert unit is not None
        assert (unit.unit_name, unit.star_level, unit.cost) == ("Carry", 2, 4)
        assert item is not None and item.item_name == "ItemA"
        assert [
            row.item_name
            for row in session.scalars(
                select(UnitItem)
                .where(UnitItem.match_id == "m1", UnitItem.puuid == "p1")
                .order_by(UnitItem.unit_idx, UnitItem.item_slot)
            )
        ] == ["ItemA", "ItemB", "ItemC", "TankItem"]
        assert result["backfill"]["excess_item_rows_skipped"] == 1
        assert trait is not None
        assert (trait.num_units, trait.style, trait.tier_current, trait.tier_total) == (
            4,
            2,
            1,
            3,
        )
        assert result["validation"]["orphans"] == {
            "player_boards": 0,
            "board_units": 0,
            "unit_items": 0,
            "board_traits": 0,
        }
        assert set(result["renamed_legacy_tables"]) >= {
            "matches_legacy",
            "participants_legacy",
            "participant_units_legacy",
            "participant_unit_items_legacy",
            "participant_traits_legacy",
            "board_units_legacy",
        }
        inspector = inspect(engine)
        assert {"matches", "matches_legacy", "board_units", "board_units_legacy"} <= set(
            inspector.get_table_names()
        )

    engine.dispose()


def test_preflight_logs_regular_progress(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_legacy(engine)
    monkeypatch.setattr(migration, "PREFLIGHT_PROGRESS_ROWS", 1)
    with Session(engine) as session:
        session.add(
            AllMatch(
                match_id="m1",
                puuid="p1",
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
        session.add(
            LegacyPlayerBoard(
                match_id="m1",
                puuid="p1",
                comp_code="Carry",
                star_levels="2",
                traits="Trait_1",
                placement=1,
            )
        )
        session.add(
            LegacyPlayerUnit(
                match_id="m1",
                puuid="p1",
                unit_name="Carry",
                unit_idx=0,
                star_level=2,
                item1="A",
                placement=1,
                cost=4,
            )
        )
        session.commit()

        with caplog.at_level(logging.INFO, logger=migration.logger.name):
            migration_preflight(session)

    messages = [record.getMessage() for record in caplog.records]
    assert messages[0] == "preflight started"
    assert any("preflight progress stage=match_metadata rows=1" in m for m in messages)
    assert any("preflight progress stage=packed_traits rows=1" in m for m in messages)
    assert any("preflight progress stage=packed_items rows=1" in m for m in messages)
    assert messages[-1].startswith("preflight complete matches=1 participants=1")
    engine.dispose()


def test_main_full_migration_does_not_run_an_extra_preflight(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class FakeSession:
        def close(self) -> None:
            pass

    fake_session = FakeSession()
    monkeypatch.setattr(migration, "load_config", lambda: None)
    monkeypatch.setattr(migration, "resolve_database_target", lambda _dsn: "target")
    monkeypatch.setattr(migration, "engine_for", lambda _target: object())
    monkeypatch.setattr(
        migration,
        "sessionmaker",
        lambda **_kwargs: lambda: fake_session,
    )
    monkeypatch.setattr(
        migration,
        "migration_preflight",
        lambda _session: pytest.fail("main ran a duplicate preflight"),
    )
    calls = []

    def fake_migrate(session, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((session, kwargs))
        return {"ok": True}

    monkeypatch.setattr(migration, "migrate_relational_v2", fake_migrate)

    migration.main([])

    assert calls == [
        (
                fake_session,
                {
                    "batch_size": 500,
                    "build_analytics": True,
                    "rename_legacy": True,
                    "resolver_factory": migration.get_patch_resolver,
                },
            )
        ]
    assert '"ok": true' in capsys.readouterr().out


def test_backfill_uses_bounded_keyset_pages_and_replays_as_skips(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analytics, "load_config", _config)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_legacy(engine)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        common = {
            "region": "americas",
            "platform": "na1",
            "game_datetime": 1,
            "game_length": 1800.0,
            "queue_id": 1100,
            "tft_set_number": 15,
            "tft_set_core_name": "TFTSet15",
            "ingested_at": 1,
        }
        session.add_all(
            AllMatch(
                match_id=f"m{index}",
                puuid=f"p{index}",
                game_version=f"Version 16.{index + 10}.1",
                patch=f"16.{index + 10}",
                **common,
            )
            for index in range(5)
        )
        session.commit()

        batches: list[list[str]] = []
        original = migration._backfill_batch

        def record_batch(*args, **kwargs):  # type: ignore[no-untyped-def]
            match_ids = kwargs.get("match_ids", args[4])
            batches.append(list(match_ids))
            return original(*args, **kwargs)

        monkeypatch.setattr(migration, "_backfill_batch", record_batch)
        with caplog.at_level(logging.INFO, logger=migration.logger.name):
            first = migration.backfill_normalized_tables(session, batch_size=2)

        assert batches == [["m0", "m1"], ["m2", "m3"], ["m4"]]
        assert first == {
            "malformed_trait_segments_skipped": 0,
            "player_boards": 5,
            "raw_matches": 5,
        }
        backfill_messages = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("raw backfill batch complete")
        ]
        assert len(backfill_messages) == 3
        assert "batch=1 source_matches=2 migrated_matches=2" in backfill_messages[0]
        assert "cumulative_source_matches=5 cumulative_migrated_matches=5" in (
            backfill_messages[-1]
        )
        first_scope_page = migration._scope_group_page(
            session,
            cursor=None,
            batch_size=2,
        )
        second_scope_page = migration._scope_group_page(
            session,
            cursor=first_scope_page[-1],
            batch_size=2,
        )
        final_scope_page = migration._scope_group_page(
            session,
            cursor=second_scope_page[-1],
            batch_size=2,
        )
        assert first_scope_page + second_scope_page + final_scope_page == [
            (f"16.{index + 10}", 1100, 15) for index in range(5)
        ]

        with caplog.at_level(logging.INFO, logger=migration.logger.name):
            analysis = migration.build_all_analysis_scopes(session, batch_size=2)

        assert len(analysis["scopes"]) == 5
        assert list(session.scalars(select(Match.match_id))) == ["m0"]
        analytics_messages = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("analytics batch complete")
        ]
        assert len(analytics_messages) == 5
        assert all("processed_matches=1 boards=1" in message for message in analytics_messages)

        batches.clear()
        replay = migration.backfill_normalized_tables(session, batch_size=2)

        assert batches == [["m0", "m1"], ["m2", "m3"], ["m4"]]
        assert replay == {"skipped_existing_matches": 5}

    engine.dispose()


def test_migration_backfills_exact_items_and_reports_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analytics, "load_config", _config)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_legacy(engine)
    with Session(engine, expire_on_commit=False) as session:
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
                AllMatch(match_id="m1", puuid="p1", **common),
                LegacyPlayerBoard(
                    match_id="m1",
                    puuid="p1",
                    comp_name=None,
                    comp_code="Carry#Carry",
                    star_levels="21",
                    traits="Trait_With_Underscores_3#bad_segment",
                    placement=1,
                ),
                LegacyPlayerUnit(
                    match_id="m1",
                    puuid="p1",
                    unit_name="Carry",
                    unit_idx=0,
                    star_level=2,
                    item1="A",
                    item2="A",
                    item3=None,
                    placement=1,
                    cost=4,
                ),
                LegacyPlayerUnit(
                    match_id="m1",
                    puuid="p1",
                    unit_name="Carry",
                    unit_idx=1,
                    star_level=1,
                    item1="B",
                    item2=None,
                    item3=None,
                    placement=1,
                    cost=4,
                ),
            ]
        )
        session.commit()
        session.execute(
            text(
                "CREATE TABLE unit_stats (tft_set_number INTEGER, unit_name TEXT, "
                "star_level INTEGER, games INTEGER)"
            )
        )
        session.commit()

        preflight = migration_preflight(session)
        result = migrate_relational_v2(
            session,
            batch_size=1,
            build_analytics=False,
            rename_legacy=False,
        )
        session.add_all(
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
        session.commit()
        analytics.rebuild_query_tables(session)

        assert preflight["nondeterministic_conflicts"] == 0
        assert preflight["malformed_trait_segments"] == 1
        assert preflight["item_representations"]["unit_item_column_instances"] == 3
        assert session.get(RawMatch, "m1") is not None
        items = session.scalars(
            select(UnitItem).order_by(UnitItem.unit_idx, UnitItem.item_slot)
        ).all()
        assert [(row.unit_idx, row.item_slot, row.item_name) for row in items] == [
            (0, 0, "A"),
            (0, 1, "A"),
            (1, 0, "B"),
        ]
        trait = session.scalar(select(BoardTrait))
        assert (trait.trait_name, trait.tier_current) == (
            "Trait_With_Underscores",
            3,
        )
        assert result["validation"]["orphans"] == {
            "player_boards": 0,
            "board_units": 0,
            "unit_items": 0,
            "board_traits": 0,
        }
        scope = session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))
        assert scope.universe_boards == 1
        assert "unit_stats_legacy" in result["renamed_legacy_tables"]

    engine.dispose()


def test_preflight_conflict_aborts_before_cutover() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    _create_legacy(engine)
    with Session(engine) as session:
        common = {
            "region": "americas",
            "platform": "na1",
            "game_datetime": 1,
            "game_length": 1800.0,
            "game_version": "Version 16.10.1",
            "queue_id": 1100,
            "tft_set_number": 15,
            "tft_set_core_name": "TFTSet15",
            "ingested_at": 1,
        }
        session.add_all(
            [
                AllMatch(match_id="m1", puuid="p1", patch="16.10", **common),
                AllMatch(match_id="m1", puuid="p2", patch="16.11", **common),
            ]
        )
        session.commit()

        with pytest.raises(MigrationConflictError):
            migrate_relational_v2(session, build_analytics=False)

        assert not inspect(engine).has_table("raw_matches")
    engine.dispose()
