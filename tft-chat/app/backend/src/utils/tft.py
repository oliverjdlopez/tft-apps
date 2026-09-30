"""Utilities for working with Community Dragon TFT static data.

The :mod:`core.models` module gives us typed views of the Community Dragon
payload (``CDragonChampion``, ``CDragonTrait``, ``CDragonItem``,
``CDragonSet``, ``CDragonData``). This module turns those models into the
lookups callers actually need when they only have a raw match payload or a
human-typed name to work from:

* **Name <-> apiName resolution.** Match payloads can carry API identifiers
  (``TFT15_Ashe``, ``TFT_Item_InfinityEdge``), while ingestion stores resolved
  display names when available. The :class:`TFTNameResolver` indexes a set's
  champions, traits, and global item list so either direction resolves.

* **Item typing.** Whether an apiName is a component, a craftable completed
  item, a trait emblem (and which trait it grants), a radiant/artifact
  variant, etc. Classification uses the CDragon data (``composition``,
  ``associatedTraits``, ``unique``) where a resolver is available and falls
  back to stable apiName heuristics via the pure module-level helpers, so
  callers that only have an apiName string can still classify it.

* **Entity detail accessors.** Unit cost/traits, trait breakpoints and
  activation styles, item components and what a component builds into.

Most helpers do not fetch: callers pass already-fetched models. The resolver's
async convenience constructor creates a short-lived ``core.cdragon.CDragon``
client itself. This keeps the lookup and classification paths easy to test.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional, Sequence

from constants import ItemTypes, TFTObjectTypes
from core.items import COMPONENT_ITEM_API_NAMES, is_component_item
from core.models import (
    CDragonChampion,
    CDragonData,
    CDragonItem,
    CDragonSet,
    CDragonTrait,
)

__all__ = [
    "is_component_item",
    "is_emblem_item",
    "is_radiant_item",
    "is_artifact_item",
    "classify_item_name",
    "TFTNameResolver",
]


# The basic component that, combined with a second component, crafts a spatula
# emblem. Used to tell craftable emblems from uncraftable ones.
_SPATULA_API_NAME = "TFT_Item_Spatula"
_FON_NAMES = frozenset(
    {
        "tacticianscape",
        "tacticianscrown",
        "tacticiansshield",
        "forceofnature",
    }
)

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize_name(text: str | None) -> str:
    """Collapse a name to a case/spacing/punctuation-insensitive key.

    ``"Jarvan IV"`` and ``"Kai'Sa"`` become ``"jarvaniv"`` / ``"kaisa"`` so
    display names, apiNames, and loosely typed user input all land on the same
    lookup key.

    Args:
        text: Display name, API name, or user-entered TFT entity name.

    Returns:
        A case-, spacing-, and punctuation-insensitive lookup key.
    """
    if not text:
        return ""
    return _NORMALIZE_RE.sub("", text.lower())


# ---------------------------------------------------------------------------
# Pure, apiName-only item helpers
#
# These need no fetched data -- they classify from the stable apiName string
# alone, so callers holding only a match-payload item id can still use them.
# The data-aware methods on TFTNameResolver refine these using composition and
# associatedTraits when the CDragon item is available.
# ---------------------------------------------------------------------------


def is_emblem_item(api_name: str | None) -> bool:
    """Whether an apiName is a trait emblem (grants a trait when equipped)."""
    if not api_name:
        return False
    return "Emblem" in api_name or "_Trait" in api_name


def is_radiant_item(api_name: str | None) -> bool:
    """Whether an apiName is the radiant (upgraded) variant of an item."""
    return bool(api_name) and "Radiant" in api_name


def is_artifact_item(api_name: str | None) -> bool:
    """Whether an apiName is an artifact / Ornn item."""
    if not api_name:
        return False
    return "Artifact" in api_name or "Ornn" in api_name


def _contains_item_marker(item: CDragonItem | None, api_name: str, marker: str) -> bool:
    """Return whether item identity or Community Dragon tags contain a marker.

    Args:
        item: Resolved Community Dragon item, when available.
        api_name: Canonical or fallback item API name.
        marker: Normalized family marker to locate.

    Returns:
        Whether the marker occurs in the normalized API name or item tags.
    """
    values = [api_name, *((item.tags or ()) if item is not None else ())]
    return any(marker in _normalize_name(value) for value in values)


def classify_item_name(api_name: str | None) -> Optional[ItemTypes]:
    """Best-effort item classification from the apiName alone.

    Returns an :class:`ItemTypes` member, or ``None`` for basic components
    (which have no ``ItemTypes`` value) and for empty input. Detection is
    limited to categories that are stable in the apiName string. Unresolved
    completed items return :attr:`ItemTypes.UNKNOWN`; only Community Dragon
    composition metadata can establish that an otherwise-unmarked item is
    craftable. Use :meth:`TFTNameResolver.classify_item` when fetched metadata
    is available.
    """
    if not api_name:
        return None
    if is_component_item(api_name):
        return None
    if is_radiant_item(api_name):
        return ItemTypes.RADIANT
    if is_artifact_item(api_name):
        return ItemTypes.ARTIFACT
    normalized = _normalize_name(api_name)
    if "support" in normalized:
        return ItemTypes.SUPPORT
    if "anima" in normalized:
        return ItemTypes.ANIMA
    if "psionic" in normalized:
        return ItemTypes.PSIONIC
    if is_emblem_item(api_name):
        return ItemTypes.EMBLEM
    if any(name in normalized for name in _FON_NAMES):
        return ItemTypes.FON
    return ItemTypes.UNKNOWN


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _select_set(data: CDragonData, set_number: int | None) -> CDragonSet:
    """Pick a set out of a CDragonData payload (mirrors core.cdragon)."""
    sets: list[CDragonSet] = data.set_data or list(data.sets.values())
    if not sets:
        raise ValueError("Community Dragon data contains no TFT sets")
    if set_number is not None:
        for s in sets:
            if s.number is not None and float(s.number) == float(set_number):
                return s
        raise ValueError(f"TFT set {set_number} not found in Community Dragon data")
    return max(sets, key=lambda s: float(s.number) if s.number is not None else -1.0)


class TFTNameResolver:
    """Bidirectional name/apiName lookups over one TFT set's static data.

    Champions and traits are set-scoped; items are global to the payload.
    Construct directly from already-fetched models, or via
    :meth:`from_set` / :meth:`from_data`.

    Lookups accept either an apiName or a display name and fall back to a
    normalized match (see :meth:`normalize_name`), so ``"Infinity Edge"``,
    ``"infinity edge"``, and ``"TFT_Item_InfinityEdge"`` all resolve.
    """

    def __init__(
        self,
        *,
        champions: Iterable[CDragonChampion] = (),
        traits: Iterable[CDragonTrait] = (),
        items: Iterable[CDragonItem] = (),
        set_number: int | None = None,
    ) -> None:
        self.set_number = set_number
        self.champions: list[CDragonChampion] = list(champions)
        self.traits: list[CDragonTrait] = list(traits)
        self.items: list[CDragonItem] = list(items)

        self._units_by_key: dict[str, CDragonChampion] = _index(self.champions)
        self._traits_by_key: dict[str, CDragonTrait] = _index(self.traits)
        self._items_by_key: dict[str, CDragonItem] = _index(self.items)

    @staticmethod
    def normalize_name(text: str | None) -> str:
        """Return the canonical lookup key used by TFT name resolution.

        Args:
            text: Display name, API name, or user-entered TFT entity name.

        Returns:
            A case-, spacing-, and punctuation-insensitive lookup key.

        This static entry point lets callers share the resolver's identity
        rules without constructing a resolver or maintaining another
        normalization implementation.
        """
        return _normalize_name(text)

    # -- constructors -------------------------------------------------------

    @classmethod
    def from_set(
        cls,
        set_obj: CDragonSet,
        items: Iterable[CDragonItem] = (),
    ) -> "TFTNameResolver":
        """Build from a single :class:`CDragonSet` plus the global item list."""
        return cls(
            champions=set_obj.champions,
            traits=set_obj.traits,
            items=items,
            set_number=int(set_obj.number) if set_obj.number is not None else None,
        )

    @classmethod
    def from_data(
        cls,
        data: CDragonData,
        set_number: int | None = None,
    ) -> "TFTNameResolver":
        """Build from a full :class:`CDragonData` payload.

        ``set_number`` selects the set; omit it for the highest-numbered set
        present, matching the "current set" behaviour in ``core.cdragon``.
        """
        chosen = _select_set(data, set_number)
        return cls.from_set(chosen, items=data.items)

    @classmethod
    async def from_latest(
        cls,
        set_number: int | None = None,
        *,
        patch: str = "latest",
    ) -> "TFTNameResolver":
        """Build by fetching Community Dragon data directly.

        Convenience for callers that just want a resolver without wiring up a
        :class:`~core.cdragon.CDragon` client themselves. Opens a client,
        fetches, and closes it again; callers that already hold a fetched
        :class:`CDragonData` payload (or make many resolvers) should use
        :meth:`from_data` instead to avoid a fetch per call.
        """
        # Imported locally: core.cdragon pulls in pulsefire/aiohttp, which
        # callers that only ever use from_set/from_data shouldn't need.
        from core.cdragon import CDragon

        cdragon = CDragon(patch=patch)
        try:
            data = await cdragon.raw()
        finally:
            await cdragon.aclose()
        return cls.from_data(data, set_number=set_number)

    # -- unit accessors -----------------------------------------------------

    def unit(self, name_or_api: str) -> Optional[CDragonChampion]:
        """Resolve a champion by apiName or display name."""
        return _lookup(self._units_by_key, name_or_api)

    def unit_api_name(self, name_or_api: str) -> Optional[str]:
        """Canonical apiName for a champion (``"Ashe"`` -> ``"TFT15_Ashe"``)."""
        u = self.unit(name_or_api)
        return u.apiName if u else None

    def unit_name(self, name_or_api: str) -> Optional[str]:
        """Display name for a champion (``"TFT15_Ashe"`` -> ``"Ashe"``)."""
        u = self.unit(name_or_api)
        return (u.name or u.apiName) if u else None

    def unit_cost(self, name_or_api: str) -> Optional[int]:
        """Shop gold cost of a champion (1-5), or ``None`` if unknown."""
        u = self.unit(name_or_api)
        return u.cost if u else None

    def unit_traits(self, name_or_api: str) -> list[str]:
        """A champion's traits as CDragon lists them (display names)."""
        u = self.unit(name_or_api)
        return list(u.traits) if u else []

    def unit_trait_api_names(self, name_or_api: str) -> list[str]:
        """A champion's traits resolved to trait apiNames where possible.

        CDragon stores a champion's traits as display names; this maps each to
        its apiName, falling back to the original string if it does not resolve
        (e.g. cross-set data).
        """
        out: list[str] = []
        for trait_name in self.unit_traits(name_or_api):
            out.append(self.trait_api_name(trait_name) or trait_name)
        return out

    # -- trait accessors ----------------------------------------------------

    def trait(self, name_or_api: str) -> Optional[CDragonTrait]:
        """Resolve a trait by apiName or display name."""
        return _lookup(self._traits_by_key, name_or_api)

    def trait_api_name(self, name_or_api: str) -> Optional[str]:
        """Canonical apiName for a trait (``"Slayer"`` -> ``"TFT15_Slayer"``)."""
        t = self.trait(name_or_api)
        return t.apiName if t else None

    def trait_name(self, name_or_api: str) -> Optional[str]:
        """Display name for a trait (``"TFT15_Slayer"`` -> ``"Slayer"``)."""
        t = self.trait(name_or_api)
        return (t.name or t.apiName) if t else None

    def trait_breakpoints(self, name_or_api: str) -> list[int]:
        """Sorted unique unit counts that activate a trait's tiers.

        e.g. ``[2, 4, 6]`` for a 2/4/6 trait. Derived from each effect's
        ``min_units``.
        """
        t = self.trait(name_or_api)
        if not t:
            return []
        counts = {e.min_units for e in t.effects if e.min_units is not None}
        return sorted(counts)

    def trait_styles(self, name_or_api: str) -> list[tuple[int, int]]:
        """``(min_units, style)`` pairs for a trait, ordered by breakpoint.

        ``style`` matches Riot's activation styles (1=bronze, 3=silver,
        4=gold, 5=prismatic). Effects missing either value are skipped.
        """
        t = self.trait(name_or_api)
        if not t:
            return []
        pairs = [
            (e.min_units, e.style)
            for e in t.effects
            if e.min_units is not None and e.style is not None
        ]
        return sorted(pairs)

    # -- item accessors -----------------------------------------------------

    def item(self, name_or_api: str) -> Optional[CDragonItem]:
        """Resolve an item by apiName or display name."""
        return _lookup(self._items_by_key, name_or_api)

    def item_api_name(self, name_or_api: str) -> Optional[str]:
        """Canonical apiName for an item (``"Infinity Edge"`` -> apiName)."""
        i = self.item(name_or_api)
        return i.apiName if i else None

    def item_name(self, name_or_api: str) -> Optional[str]:
        """Display name for an item, falling back to its apiName."""
        i = self.item(name_or_api)
        return (i.name or i.apiName) if i else None

    def item_components(self, name_or_api: str) -> list[str]:
        """The component apiNames an item is built from (empty for basics)."""
        i = self.item(name_or_api)
        return list(i.composition) if i else []

    def items_built_from(self, component_name_or_api: str) -> list[str]:
        """Every item whose composition includes this component."""
        comp_api = self.item_api_name(component_name_or_api) or component_name_or_api
        return [i.apiName for i in self.items if comp_api in i.composition]

    def is_component(self, name_or_api: str) -> bool:
        """Whether an item is a basic component.

        Resolves the input to its canonical apiName first so a display name
        (``"B. F. Sword"``) classifies the same as its apiName.
        """
        api = self.item_api_name(name_or_api) or name_or_api
        return is_component_item(api)

    def is_emblem(self, name_or_api: str) -> bool:
        """Whether an item is a trait emblem (grants a trait)."""
        i = self.item(name_or_api)
        if i is not None and i.associated_traits:
            return True
        return is_emblem_item(self.item_api_name(name_or_api) or name_or_api)

    def emblem_trait(self, name_or_api: str) -> Optional[str]:
        """The trait apiName an emblem grants, or ``None`` if it is not one."""
        i = self.item(name_or_api)
        if i and i.associated_traits:
            return i.associated_traits[0]
        return None

    def classify_item(self, name_or_api: str) -> Optional[ItemTypes]:
        """Data-backed item classification into an :class:`ItemTypes` member.

        Refines :func:`classify_item_name` using the fetched item: emblems are
        split into craftable (:attr:`ItemTypes.EMBLEM`, built with a Spatula)
        vs :attr:`ItemTypes.UNCRAFTABLE_EMBLEM`. Returns ``None`` for basic
        components. Falls back to apiName heuristics for unresolved input.
        """
        i = self.item(name_or_api)
        if i is None:
            return classify_item_name(name_or_api)

        api = i.apiName
        if api in COMPONENT_ITEM_API_NAMES:
            return None
        if _contains_item_marker(i, api, "radiant"):
            return ItemTypes.RADIANT
        if _contains_item_marker(i, api, "artifact") or _contains_item_marker(
            i, api, "ornn"
        ):
            return ItemTypes.ARTIFACT
        if _contains_item_marker(i, api, "support"):
            return ItemTypes.SUPPORT
        if _contains_item_marker(i, api, "anima"):
            return ItemTypes.ANIMA
        if _contains_item_marker(i, api, "psionic"):
            return ItemTypes.PSIONIC
        if i.associated_traits or is_emblem_item(api):
            if _SPATULA_API_NAME in i.composition:
                return ItemTypes.EMBLEM
            return ItemTypes.UNCRAFTABLE_EMBLEM
        normalized_identity = _normalize_name(f"{api} {i.name or ''}")
        if any(name in normalized_identity for name in _FON_NAMES):
            return ItemTypes.FON
        if i.composition:
            return ItemTypes.CRAFTABLE
        # A unique item with no composition and no trait is something bespoke.
        return ItemTypes.SPECIAL if i.unique else ItemTypes.UNKNOWN

    # -- generic ------------------------------------------------------------

    def object_type(self, name_or_api: str) -> Optional[TFTObjectTypes]:
        """Classify a name/apiName as a unit, trait, or item (or ``None``).

        Units and traits are checked before items so an apiName that only
        exists in one index resolves unambiguously.
        """
        if self.unit(name_or_api) is not None:
            return TFTObjectTypes.UNIT
        if self.trait(name_or_api) is not None:
            return TFTObjectTypes.TRAIT
        if self.item(name_or_api) is not None:
            return TFTObjectTypes.ITEM
        return None

    def api_name(self, name_or_api: str) -> Optional[str]:
        """Resolve any unit/trait/item name to its apiName."""
        return (
            self.unit_api_name(name_or_api)
            or self.trait_api_name(name_or_api)
            or self.item_api_name(name_or_api)
        )

    def display_name(self, name_or_api: str) -> Optional[str]:
        """Resolve any unit/trait/item apiName to its display name."""
        return (
            self.unit_name(name_or_api)
            or self.trait_name(name_or_api)
            or self.item_name(name_or_api)
        )

    def resolve(self, name_or_api: str) -> Optional[tuple[TFTObjectTypes, str]]:
        """Resolve a name to its ``(object_type, apiName)`` pair, or ``None``."""
        kind = self.object_type(name_or_api)
        if kind is None:
            return None
        api = self.api_name(name_or_api)
        return (kind, api) if api else None


# ---------------------------------------------------------------------------
# Indexing internals
# ---------------------------------------------------------------------------


def _index(entities: Sequence) -> dict:
    """Map both apiName and normalized display name to each entity.

    apiName keys win over display-name keys on collision (apiNames are
    canonical and unique), and earlier entities win over later ones so the
    result is deterministic.
    """
    by_key: dict[str, object] = {}
    # First pass: exact + normalized apiNames (canonical, never overwritten).
    for e in entities:
        api = getattr(e, "apiName", "") or ""
        if not api:
            continue
        by_key.setdefault(api, e)
        by_key.setdefault(TFTNameResolver.normalize_name(api), e)
    # Second pass: normalized display names, not overwriting apiName keys.
    for e in entities:
        key = TFTNameResolver.normalize_name(getattr(e, "name", None))
        if key:
            by_key.setdefault(key, e)
    return by_key


def _lookup(by_key: dict, name_or_api: str):
    """Look up an entity by exact apiName, then normalized name/apiName."""
    if not name_or_api:
        return None
    hit = by_key.get(name_or_api)
    if hit is not None:
        return hit
    return by_key.get(TFTNameResolver.normalize_name(name_or_api))
