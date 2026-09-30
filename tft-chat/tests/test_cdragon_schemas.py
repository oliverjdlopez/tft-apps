from __future__ import annotations

from core.models import (
    CDragonChampion,
    CDragonData,
    CDragonItem,
    CDragonSet,
    CDragonTrait,
)


def _payload() -> dict[str, object]:
    champion = {
        "apiName": "TFT_Test_Unit",
        "characterName": "TFT_Test_Unit",
        "cost": 4,
        "name": "Test Unit",
        "role": "APCaster",
        "traits": ["Test Trait"],
        "ability": {
            "name": "Test Spell",
            "desc": "Deal damage.",
            "variables": [{"name": "Damage", "value": [100.0, 200.0, 300.0]}],
        },
        "stats": {
            "armor": 30.0,
            "attackSpeed": 0.75,
            "damage": 50.0,
            "hp": 800.0,
            "initialMana": 20,
            "magicResist": 30.0,
            "mana": 80,
            "range": 4,
        },
        "futureChampionField": True,
    }
    trait = {
        "apiName": "TFT_Test_Trait",
        "name": "Test Trait",
        "desc": "Gain power.",
        "icon": "trait.tex",
        "effects": [
            {
                "minUnits": 2,
                "maxUnits": 3,
                "style": 1,
                "variables": {"Power": 10.0},
            }
        ],
    }
    item = {
        "apiName": "TFT_Item_Test",
        "name": "Test Item",
        "desc": "An item.",
        "composition": ["TFT_Item_Component"],
        "effects": {"Damage": 10.0},
        "from": None,
        "tags": ["AD"],
        "unique": False,
    }
    set_data = {
        "number": 99,
        "name": "Test Set",
        "mutator": "TFTSet99",
        "augments": ["TFT_Augment_Test"],
        "items": ["TFT_Item_Test"],
        "champions": [champion],
        "traits": [trait],
    }
    return {
        "items": [item],
        "setData": [set_data],
        "sets": {"99": set_data},
        "futureTopLevelField": {},
    }


def test_cdragon_schema_parses_nested_payload_and_aliases() -> None:
    parsed = CDragonData.model_validate(_payload())

    assert isinstance(parsed.items[0], CDragonItem)
    assert isinstance(parsed.set_data[0], CDragonSet)
    assert isinstance(parsed.set_data[0].champions[0], CDragonChampion)
    assert isinstance(parsed.set_data[0].traits[0], CDragonTrait)
    assert parsed.set_data[0].champions[0].stats.attack_speed == 0.75
    assert parsed.set_data[0].traits[0].effects[0].min_units == 2
    assert parsed.set_data[0].items == ["TFT_Item_Test"]
    assert parsed.set_data[0].get("mutator") == "TFTSet99"
    assert parsed.set_data[0].champions[0].get("apiName") == "TFT_Test_Unit"
