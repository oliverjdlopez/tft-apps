from __future__ import annotations

import argparse

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from db.models import (
    AllMatch,
    Base,
    BoardTrait,
    LegacyPlayerUnit,
    PlayerBoard,
    PlayerItem,
    PlayerUnit,
    RawMatch,
)
from scripts.update_tables import fn as fn_module
from scripts.update_tables import main as update_cli


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


def _match(match_id: str, puuid: str, patch: str | None) -> AllMatch:
    return AllMatch(
        match_id=match_id,
        puuid=puuid,
        region="americas",
        platform="na1",
        game_datetime=1,
        game_length=1800.0,
        game_version="Version 16.11.123",
        patch=patch,
        queue_id=1100,
        tft_set_number=15,
        tft_set_core_name="TFTSet15",
        ingested_at=1,
    )


def test_dientity_is_a_noop_table_update(session) -> None:
    session.add(_match("m1", "p1", "16.10"))
    session.commit()

    updated = fn_module.dientity(session, "all_matches")

    assert updated == 1
    assert session.query(AllMatch).one().patch == "16.10"


def test_update_table_invokes_named_table_function(session) -> None:
    session.add_all([_match("m1", "p1", "16.10"), _match("m2", "p2", "16.10")])
    session.commit()

    def bump_patch(session_arg, table_arg: str, *, batch_size: int) -> int:
        assert session_arg is session
        assert table_arg == "all_matches"
        assert batch_size == update_cli.DEFAULT_BATCH_SIZE
        count = session.query(AllMatch).update(
            {AllMatch.patch: "16.11"}, synchronize_session=False
        )
        session.commit()
        return count

    updated = update_cli.update_table(session, "all_matches", bump_patch)

    assert updated == 2
    assert {row.patch for row in session.query(AllMatch).all()} == {"16.11"}


def test_update_table_dientity_is_a_noop(session) -> None:
    session.add(_match("m1", "p1", "16.10"))
    session.commit()

    updated = update_cli.update_table(session, "all_matches", fn_module.dientity)

    assert updated == 1
    assert session.query(AllMatch).one().patch == "16.10"


def test_update_table_unknown_table_raises(session) -> None:
    with pytest.raises(ValueError):
        update_cli.update_table(session, "not_a_table", fn_module.dientity)


def test_resolve_names_updates_relevant_columns(monkeypatch, session) -> None:
    class FakeResolver:
        def __init__(self, set_number: int | None) -> None:
            self.set_number = set_number

        def display_name(self, value: str) -> str | None:
            return {
                "TFT15_Ashe": "Ashe",
                "TFT15_Leona": "Leona",
                "TFT_Item_InfinityEdge": "Infinity Edge",
                "TFT_Item_BFSword": "B. F. Sword",
            }.get(value)

        def trait_name(self, value: str) -> str | None:
            return {"TFT15_CrystalGambit": "Crystal Gambit"}.get(value)

    monkeypatch.setattr(
        fn_module, "_get_resolver", lambda set_number: FakeResolver(set_number)
    )
    session.add(_match("m1", "p1", "16.10"))
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
    session.add(
        PlayerBoard(
            match_id="m1",
            puuid="p1",
            comp_code="TFT15_Ashe#TFT15_Leona",
            star_levels="11",
            traits="TFT15_CrystalGambit_3",
        )
    )
    session.add(
        PlayerItem(
            match_id="m1",
            puuid="p1",
            unit_name="TFT15_Ashe",
            item_name="TFT_Item_InfinityEdge",
            idx=0,
            placement=1,
            other_item1="TFT_Item_BFSword",
        )
    )
    session.add(
        PlayerUnit(
            match_id="m1",
            puuid="p1",
            unit_name="TFT15_Ashe",
            unit_idx=0,
            star_level=2,
            item1="TFT_Item_InfinityEdge",
            placement=1,
            cost=5,
        )
    )
    session.commit()

    trait_updates = fn_module.resolve_names(session, "board_traits")
    item_updates = fn_module.resolve_names(session, "unit_items")
    unit_updates = fn_module.resolve_names(session, "board_units")

    board = session.query(PlayerBoard).one()
    item = session.query(PlayerItem).one()
    unit = session.query(PlayerUnit).one()
    trait = session.query(BoardTrait).one()
    assert trait_updates == 1
    assert trait.trait_name == "Crystal Gambit"
    assert item_updates == 1
    assert item.unit_name == "Ashe"
    assert item.item_name == "Infinity Edge"
    assert unit_updates == 1
    assert unit.unit_name == "Ashe"
    assert unit.item1 == "Infinity Edge"


def test_resolve_names_renames_legacy_columns_before_querying(monkeypatch, session) -> None:
    class FakeResolver:
        def __init__(self, set_number: int | None) -> None:
            self.set_number = set_number

        def display_name(self, value: str) -> str | None:
            return {"TFT15_Ashe": "Ashe"}.get(value)

    monkeypatch.setattr(
        fn_module, "_get_resolver", lambda set_number: FakeResolver(set_number)
    )
    session.add(_match("m1", "p1", "16.10"))
    session.add(
        LegacyPlayerUnit(
            match_id="m1",
            puuid="p1",
            unit_name="TFT15_Ashe",
            unit_idx=0,
            star_level=2,
            placement=1,
            cost=5,
        )
    )
    session.commit()
    session.execute(text("ALTER TABLE player_units RENAME COLUMN unit_name TO name"))
    session.commit()

    assert fn_module.resolve_names(session, "player_units") == 1

    columns = {column["name"] for column in inspect(session.bind).get_columns("player_units")}
    unit = session.query(LegacyPlayerUnit).one()
    assert "unit_name" in columns
    assert "name" not in columns
    assert unit.unit_name == "Ashe"


def test_rename_field_names_renames_legacy_columns(session) -> None:
    session.execute(text("ALTER TABLE player_units RENAME COLUMN unit_name TO name"))
    session.commit()

    assert fn_module.rename_field_names(session, "player_units") == 1
    columns = {column["name"] for column in inspect(session.bind).get_columns("player_units")}
    assert "unit_name" in columns
    assert "name" not in columns


def test_rename_field_names_is_idempotent_on_current_schema(session) -> None:
    assert fn_module.rename_field_names(session, "player_items") == 0


def test_update_tables_resolves_default_function_and_dsn(monkeypatch, session) -> None:
    session.add(_match("m1", "p1", "16.10"))
    session.commit()

    monkeypatch.setattr(update_cli, "open_db", lambda: session)
    monkeypatch.setattr(update_cli, "database_label", lambda: "sqlite:///:memory:")

    args = argparse.Namespace(
        tables=["all_matches"],
        function="dientity",
        dsn=None,
        batch_size=update_cli.DEFAULT_BATCH_SIZE,
    )
    result = update_cli.update_tables(args)

    assert result == {
        "database": "sqlite:///:memory:",
        "function": "dientity",
        "tables": {"all_matches": 1},
    }


def test_update_tables_unknown_function_raises(monkeypatch, session) -> None:
    monkeypatch.setattr(update_cli, "open_db", lambda: session)
    args = argparse.Namespace(
        tables=["all_matches"],
        function="does_not_exist",
        dsn=None,
        batch_size=update_cli.DEFAULT_BATCH_SIZE,
    )

    with pytest.raises(ValueError):
        update_cli.update_tables(args)
