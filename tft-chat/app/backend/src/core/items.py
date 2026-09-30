"""Shared TFT item helpers."""

from __future__ import annotations

COMPONENT_ITEM_API_NAMES = frozenset(
    {
        "TFT_Item_BFSword",
        "TFT_Item_ChainVest",
        "TFT_Item_GiantsBelt",
        "TFT_Item_NeedlesslyLargeRod",
        "TFT_Item_NegatronCloak",
        "TFT_Item_RecurveBow",
        "TFT_Item_SparringGloves",
        "TFT_Item_Spatula",
        "TFT_Item_TearOfTheGoddess",
    }
)


def is_component_item(item_name: str | None) -> bool:
    """Return whether an item API id is a basic component."""

    return item_name in COMPONENT_ITEM_API_NAMES


__all__ = ["COMPONENT_ITEM_API_NAMES", "is_component_item"]
