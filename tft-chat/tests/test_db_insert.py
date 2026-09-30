from __future__ import annotations

import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import CDragonChampion, RiotUnit
from db import insert as insert_module
from db.insert import insert_match_payload, persist_item_metadata, resolve_unit_cost
from db.models import (
    Base,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    PlayerBoard,
    PlayerItem,
    PlayerUnit,
    RawMatch,
    UnitItem,
)


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


def test_insert_match_payload_resolves_fresh_row_names(monkeypatch, session) -> None:
    class FakeResolver:
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
        insert_module,
        "_get_resolver",
        lambda patch, set_number: FakeResolver(),
    )
    payload = {
        "metadata": {"match_id": "NA1_123", "participants": ["p1"]},
        "info": {
            "game_datetime": 1,
            "game_length": 1800.0,
            "game_version": "Version 16.10.1",
            "queue_id": 1100,
            "tft_set_number": 15,
            "tft_set_core_name": "TFTSet15",
            "participants": [
                {
                    "puuid": "p1",
                    "placement": 1,
                    "traits": [
                        {
                            "name": "TFT15_CrystalGambit",
                            "style": 3,
                            "tier_current": 3,
                        }
                    ],
                    "units": [
                        {
                            "character_id": "TFT15_Ashe",
                            "tier": 2,
                            "rarity": 4,
                            "itemNames": [
                                "TFT_Item_InfinityEdge",
                                "TFT_Item_BFSword",
                            ],
                        },
                        {
                            "character_id": "TFT15_Leona",
                            "tier": 1,
                            "rarity": 1,
                            "itemNames": [],
                        },
                    ],
                }
            ],
        },
    }

    assert insert_match_payload(session, payload, region="americas", platform="na1") is True

    board = session.query(PlayerBoard).one()
    units = session.query(PlayerUnit).order_by(PlayerUnit.unit_idx).all()
    item = session.query(PlayerItem).one()
    assert board.comp_code == "Ashe#Leona"
    assert board.traits == "Crystal Gambit_3"
    assert [unit.unit_name for unit in units] == ["Ashe", "Leona"]
    assert [unit.cost for unit in units] == [5, 2]
    assert units[0].item1 == "Infinity Edge"
    assert item.unit_name == "Ashe"
    assert item.item_name == "Infinity Edge"


def test_insert_match_payload_uses_static_cost_for_zero_based_riot_rarity(
    session,
) -> None:
    """Persist the game's cost when Riot rarity and static metadata disagree."""

    class Resolver:
        set_number = 15

        def display_name(self, value: str) -> str | None:
            return "Ashe" if value == "TFT15_Ashe" else None

        def trait_name(self, value: str) -> str | None:
            return value

        def unit(self, value: str) -> CDragonChampion:
            return CDragonChampion(apiName="TFT15_Ashe", cost=4)

    payload = {
        "metadata": {"match_id": "NA1_static_cost"},
        "info": {
            "game_version": "Version 16.10.1",
            "tft_set_number": 15,
            "participants": [
                {
                    "puuid": "p1",
                    "units": [
                        {
                            "character_id": "TFT15_Ashe",
                            "tier": 1,
                            "rarity": 4,
                        }
                    ],
                }
            ],
        },
    }

    assert insert_match_payload(
        session,
        payload,
        region="americas",
        resolver=Resolver(),
    ) is True
    assert session.query(BoardUnit).one().cost == 4


def test_resolve_unit_cost_falls_back_when_static_cost_is_unavailable() -> None:
    """Retain normalized Riot cost when static unit metadata is incomplete."""

    class Resolver:
        def unit(self, value: str):
            return None

    unit = RiotUnit(character_id="TFT15_Ashe", rarity=4)

    assert resolve_unit_cost(Resolver(), unit) == 5


def test_unresolved_names_are_logged_once_per_kind_and_set(caplog) -> None:
    class FakeResolver:
        set_number = 15

        def display_name(self, value: str) -> None:
            return None

        def trait_name(self, value: str) -> None:
            return None

    resolver = FakeResolver()
    insert_module._logged_unresolved_names.clear()
    try:
        with caplog.at_level(logging.WARNING, logger="tft-ingest"):
            assert (
                insert_module._display_name(
                    resolver,
                    "TFT15_Unknown",
                    kind="unit",
                )
                == "TFT15_Unknown"
            )
            assert (
                insert_module._display_name(
                    resolver,
                    "TFT15_Unknown",
                    kind="unit",
                )
                == "TFT15_Unknown"
            )
            assert (
                insert_module._display_name(
                    resolver,
                    "TFT15_Unknown",
                    kind="item",
                )
                == "TFT15_Unknown"
            )
            assert (
                insert_module._trait_name(resolver, "TFT15_UnknownTrait")
                == "TFT15_UnknownTrait"
            )

        assert [record.message for record in caplog.records] == [
            "Unresolved TFT unit name for set 15; storing raw value 'TFT15_Unknown'",
            "Unresolved TFT item name for set 15; storing raw value 'TFT15_Unknown'",
            "Unresolved TFT trait name for set 15; storing raw value "
            "'TFT15_UnknownTrait'",
        ]
    finally:
        insert_module._logged_unresolved_names.clear()


def test_insert_builds_complete_graph_with_exact_duplicate_unit_items(session) -> None:
    class Resolver:
        set_number = 15

        def display_name(self, value: str) -> str | None:
            return {
                "TFT15_Ashe": "Ashe",
                "TFT_Item_Duplicate": "Duplicate Item",
            }.get(value)

        def trait_name(self, value: str) -> str | None:
            return {
                "TFT15_Active": "Active Trait",
                "TFT15_Inactive": "Inactive Trait",
            }.get(value)

        def item_api_name(self, value: str) -> str:
            return value

        def classify_item(self, value: str) -> str:
            return "artifact"

    payload = {
        "metadata": {
            "data_version": "5",
            "match_id": "NA1_graph",
            "participants": ["p1"],
        },
        "info": {
            "endOfGameResult": "GameComplete",
            "gameCreation": 100,
            "game_datetime": 101,
            "game_length": 1900.0,
            "game_version": "Version 16.10.9",
            "game_id": 42,
            "game_variation": "standard",
            "mapId": 22,
            "queue_id": 1100,
            "tft_game_type": "standard",
            "tft_set_number": 15,
            "tft_set_core_name": "TFTSet15",
            "participants": [
                {
                    "puuid": "p1",
                    "riotIdGameName": "Player",
                    "riotIdTagline": "NA1",
                    "placement": 1,
                    "level": 9,
                    "last_round": 38,
                    "players_eliminated": 4,
                    "total_damage_to_players": 120,
                    "gold_left": 7,
                    "time_eliminated": 1900.0,
                    "win": True,
                    "partner_group_id": 2,
                    "companion": {
                        "content_ID": "companion",
                        "item_ID": 3,
                        "skin_ID": 4,
                        "species": "pengu",
                    },
                    "traits": [
                        {
                            "name": "TFT15_Active",
                            "num_units": 6,
                            "style": 3,
                            "tier_current": 2,
                            "tier_total": 4,
                        },
                        {
                            "name": "TFT15_Inactive",
                            "num_units": 1,
                            "style": 0,
                            "tier_current": 0,
                            "tier_total": 3,
                        },
                    ],
                    "units": [
                        {
                            "character_id": "TFT15_Ashe",
                            "tier": 2,
                            "rarity": 3,
                            "itemNames": [
                                "TFT_Item_Duplicate",
                                "TFT_Item_Duplicate",
                            ],
                        },
                        {
                            "character_id": "TFT15_Ashe",
                            "tier": 1,
                            "rarity": 3,
                            "itemNames": [],
                        },
                    ],
                }
            ],
        },
    }

    assert insert_match_payload(
        session,
        payload,
        region="americas",
        platform="na1",
        resolver=Resolver(),
    ) is True
    assert insert_match_payload(
        session,
        payload,
        region="americas",
        platform="na1",
        resolver=Resolver(),
    ) is False

    match = session.query(RawMatch).one()
    board = session.query(PlayerBoard).one()
    units = session.query(BoardUnit).order_by(BoardUnit.unit_idx).all()
    items = session.query(UnitItem).order_by(UnitItem.item_slot).all()
    metadata = session.query(ItemMetadata).one()
    traits = {row.trait_name: row for row in session.query(BoardTrait)}
    assert (match.data_version, match.game_creation, match.game_id, match.map_id) == (
        "5",
        100,
        42,
        22,
    )
    assert (board.level, board.last_round, board.win, board.companion_species) == (
        9,
        38,
        True,
        "pengu",
    )
    assert [(row.unit_idx, row.unit_name, row.star_level) for row in units] == [
        (0, "Ashe", 2),
        (1, "Ashe", 1),
    ]
    assert [(row.unit_idx, row.item_slot, row.item_name) for row in items] == [
        (0, 0, "Duplicate Item"),
        (0, 1, "Duplicate Item"),
    ]
    assert {row.item_api_name for row in items} == {"TFT_Item_Duplicate"}
    assert (
        metadata.patch,
        metadata.tft_set_number,
        metadata.item_api_name,
        metadata.item_name,
        metadata.item_type,
    ) == (
        "16.10",
        15,
        "TFT_Item_Duplicate",
        "Duplicate Item",
        "artifact",
    )
    assert (traits["Active Trait"].num_units, traits["Active Trait"].tier_current) == (
        6,
        2,
    )
    assert traits["Inactive Trait"].style == 0


def test_item_metadata_rejects_conflicting_patch_set_classification(session) -> None:
    """Reject a repeated canonical identity whose classification drifts."""
    values = {
        "patch": "16.10",
        "tft_set_number": 15,
        "item_api_name": "TFT_Item_Test",
        "item_name": "Test Item",
    }
    persist_item_metadata(session, **values, item_type="artifact")
    session.flush()

    with pytest.raises(ValueError, match="Conflicting item metadata"):
        persist_item_metadata(session, **values, item_type="support")
