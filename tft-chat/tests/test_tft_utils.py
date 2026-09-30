from __future__ import annotations

from constants import ItemTypes, TFTObjectTypes
from core.models import CDragonData
from utils.tft import (
    TFTNameResolver,
    classify_item_name,
    is_emblem_item,
)


def _payload() -> dict:
    return {
        "items": [
            {"apiName": "TFT_Item_BFSword", "name": "B. F. Sword", "composition": []},
            {
                "apiName": "TFT_Item_InfinityEdge",
                "name": "Infinity Edge",
                "composition": ["TFT_Item_BFSword", "TFT_Item_SparringGloves"],
            },
            {
                "apiName": "TFT_Item_SlayerEmblem",
                "name": "Slayer Emblem",
                "composition": ["TFT_Item_Spatula", "TFT_Item_BFSword"],
                "associatedTraits": ["TFT15_Slayer"],
            },
            {
                "apiName": "TFT_Item_UncraftableSlayerEmblem",
                "name": "Special Slayer Emblem",
                "composition": [],
                "associatedTraits": ["TFT15_Slayer"],
            },
            {
                "apiName": "TFT_Item_InfinityEdgeRadiant",
                "name": "Radiant Infinity Edge",
                "composition": [],
            },
            {"apiName": "TFT_Item_Artifact_Fishbones", "name": "Fishbones"},
            {
                "apiName": "TFT_Item_Moonstone",
                "name": "Moonstone Renewer",
                "tags": ["Support"],
            },
            {"apiName": "TFT17_Item_AnimaSword", "name": "Anima Sword"},
            {"apiName": "TFT17_Item_PsionicBow", "name": "Psionic Bow"},
            {"apiName": "TFT_Item_TacticiansCrown", "name": "Tactician's Crown"},
            {"apiName": "TFT_Item_Bespoke", "name": "Bespoke", "unique": True},
        ],
        "setData": [
            {
                "number": 15,
                "name": "Set Fifteen",
                "mutator": "TFTSet15",
                "champions": [
                    {
                        "apiName": "TFT15_Ashe",
                        "name": "Ashe",
                        "cost": 1,
                        "traits": ["Slayer", "Sniper"],
                    }
                ],
                "traits": [
                    {
                        "apiName": "TFT15_Slayer",
                        "name": "Slayer",
                        "effects": [
                            {"minUnits": 2, "style": 1},
                            {"minUnits": 4, "style": 4},
                        ],
                    }
                ],
            }
        ],
        "sets": {},
    }


def _resolver() -> TFTNameResolver:
    return TFTNameResolver.from_data(CDragonData.model_validate(_payload()))


def test_normalize_name_is_case_and_punctuation_insensitive() -> None:
    assert TFTNameResolver.normalize_name("Kai'Sa") == "kaisa"
    assert TFTNameResolver.normalize_name("Jarvan IV") == "jarvaniv"
    assert TFTNameResolver.normalize_name("  B. F. Sword ") == "bfsword"
    assert TFTNameResolver.normalize_name(None) == ""


def test_from_data_selects_the_configured_set() -> None:
    r = _resolver()
    assert r.set_number == 15


def test_unit_name_and_api_name_round_trip() -> None:
    r = _resolver()
    assert r.unit_api_name("Ashe") == "TFT15_Ashe"
    assert r.unit_api_name("ashe") == "TFT15_Ashe"  # normalized fuzzy match
    assert r.unit_name("TFT15_Ashe") == "Ashe"
    assert r.unit_cost("Ashe") == 1
    assert r.unit_traits("Ashe") == ["Slayer", "Sniper"]
    # trait display names map back to apiNames where they resolve.
    assert r.unit_trait_api_names("Ashe") == ["TFT15_Slayer", "Sniper"]


def test_trait_breakpoints_and_styles() -> None:
    r = _resolver()
    assert r.trait_api_name("Slayer") == "TFT15_Slayer"
    assert r.trait_name("TFT15_Slayer") == "Slayer"
    assert r.trait_breakpoints("Slayer") == [2, 4]
    assert r.trait_styles("Slayer") == [(2, 1), (4, 4)]


def test_item_components_and_reverse_lookup() -> None:
    r = _resolver()
    assert r.item_api_name("Infinity Edge") == "TFT_Item_InfinityEdge"
    assert r.item_components("infinity edge") == [
        "TFT_Item_BFSword",
        "TFT_Item_SparringGloves",
    ]
    assert "TFT_Item_InfinityEdge" in r.items_built_from("B. F. Sword")


def test_item_classification_is_data_backed() -> None:
    r = _resolver()
    assert r.is_component("B. F. Sword") is True
    assert r.is_component("Infinity Edge") is False
    assert r.is_emblem("Slayer Emblem") is True
    assert r.emblem_trait("Slayer Emblem") == "TFT15_Slayer"

    assert r.classify_item("B. F. Sword") is None  # components have no ItemType
    assert r.classify_item("Infinity Edge") == ItemTypes.CRAFTABLE
    assert r.classify_item("Slayer Emblem") == ItemTypes.EMBLEM
    assert r.classify_item("Special Slayer Emblem") == ItemTypes.UNCRAFTABLE_EMBLEM
    assert r.classify_item("Radiant Infinity Edge") == ItemTypes.RADIANT
    assert r.classify_item("Fishbones") == ItemTypes.ARTIFACT
    assert r.classify_item("Moonstone Renewer") == ItemTypes.SUPPORT
    assert r.classify_item("Anima Sword") == ItemTypes.ANIMA
    assert r.classify_item("Psionic Bow") == ItemTypes.PSIONIC
    assert r.classify_item("Tactician's Crown") == ItemTypes.FON
    assert r.classify_item("Bespoke") == ItemTypes.SPECIAL
    assert r.classify_item("missing") == ItemTypes.UNKNOWN


def test_name_only_helpers_need_no_fetched_data() -> None:
    assert classify_item_name("TFT_Item_BFSword") is None
    assert classify_item_name("TFT_Item_InfinityEdge") == ItemTypes.UNKNOWN
    assert classify_item_name("TFT_Item_InfinityEdgeRadiant") == ItemTypes.RADIANT
    assert classify_item_name(None) is None
    assert is_emblem_item("TFT_Item_SlayerEmblem") is True
    assert is_emblem_item("TFT_Item_InfinityEdge") is False


def test_object_type_and_generic_resolution() -> None:
    r = _resolver()
    assert r.object_type("Ashe") == TFTObjectTypes.UNIT
    assert r.object_type("Slayer") == TFTObjectTypes.TRAIT
    assert r.object_type("Infinity Edge") == TFTObjectTypes.ITEM
    assert r.object_type("nonexistent") is None

    assert r.resolve("Ashe") == (TFTObjectTypes.UNIT, "TFT15_Ashe")
    assert r.api_name("infinity edge") == "TFT_Item_InfinityEdge"
    assert r.display_name("TFT15_Slayer") == "Slayer"


def test_empty_resolver_falls_back_to_name_heuristics() -> None:
    empty = TFTNameResolver()
    assert empty.unit("Ashe") is None
    # No data to resolve against, but apiName heuristics still classify.
    assert empty.classify_item("TFT_Item_InfinityEdge") == ItemTypes.UNKNOWN
    assert empty.classify_item("TFT_Item_BFSword") is None
