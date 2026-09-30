"""Insert one Riot payload as a complete normalized ORM graph."""

from __future__ import annotations

import logging
import time
from typing import Any

from core.items import is_component_item
from core.config import load_config
from core.models import RiotMatch, RiotUnit
from constants import ItemTypes
from utils.tft import TFTNameResolver, classify_item_name

from .utils import extract_patch

from sqlalchemy.orm import Session

from .models import BoardTrait, BoardUnit, ItemMetadata, PlayerBoard, RawMatch, UnitItem

logger = logging.getLogger("tft-ingest")

_resolvers: dict[tuple[str, int | None], TFTNameResolver] = {}
_logged_unresolved_names: set[tuple[int | None, str, str]] = set()


def _comp_code(unit_names: list[str]) -> str | None:
    return "#".join(unit_names) if unit_names else None


def _traits_code(traits: list[tuple[str, int]]) -> str:
    return "#".join(f"{name}_{tier}" for name, tier in traits)


def get_patch_resolver(patch: str, set_number: int | None) -> TFTNameResolver:
    """Return the cached exact-patch resolver used by match ingestion.

    Args:
        patch: Normalized patch extracted from the Riot match version.
        set_number: TFT set represented by the match.

    Returns:
        A patch/set-specific Community Dragon name resolver.
    """
    identity = (patch, set_number)
    resolver = _resolvers.get(identity)
    if resolver is None:
        import asyncio

        resolver = asyncio.run(
            TFTNameResolver.from_latest(set_number=set_number, patch=patch)
        )
        _resolvers[identity] = resolver
    return resolver


def _get_resolver(patch: str, set_number: int | None) -> TFTNameResolver:
    """Keep the insertion seam used by existing tests and callers."""
    return get_patch_resolver(patch, set_number)


def _log_unresolved_name(
    resolver: TFTNameResolver,
    value: str,
    *,
    kind: str,
) -> None:
    key = (getattr(resolver, "set_number", None), kind, value)
    if key in _logged_unresolved_names:
        return
    _logged_unresolved_names.add(key)
    logger.warning(
        "Unresolved TFT %s name for set %s; storing raw value %r",
        kind,
        key[0],
        value,
    )


def _display_name(
    resolver: TFTNameResolver,
    value: str,
    *,
    kind: str,
) -> str:
    if not value:
        return value
    resolved = resolver.display_name(value)
    if not resolved:
        _log_unresolved_name(resolver, value, kind=kind)
        return value
    return resolved


def _trait_name(resolver: TFTNameResolver, value: str) -> str:
    resolved = resolver.trait_name(value)
    if not resolved:
        _log_unresolved_name(resolver, value, kind="trait")
        return value
    return resolved


def resolve_unit_cost(resolver: TFTNameResolver, unit: RiotUnit) -> int:
    """Resolve a unit's game-facing shop cost for the match's patch and set.

    Community Dragon stores the displayed shop cost directly (1-5), while
    the Riot match payload exposes a zero-based rarity field. The exact-patch
    static catalogue is authoritative when it contains the unit; the Riot
    value remains a fallback for incomplete or unavailable catalogue data.

    Args:
        resolver: Exact-patch, set-scoped Community Dragon resolver.
        unit: Riot unit from the final-board payload.

    Returns:
        The one-based shop cost persisted on the normalized unit row.
    """
    match_cost = unit.cost
    lookup = getattr(resolver, "unit", None)
    static_unit = lookup(unit.resolved_character_id) if callable(lookup) else None
    static_cost = getattr(static_unit, "cost", None)
    if isinstance(static_cost, int) and 1 <= static_cost <= 5:
        if static_cost != match_cost:
            logger.warning(
                "Unit cost mismatch for %s in set %s: Riot rarity=%s "
                "normalized_cost=%s, Community Dragon cost=%s; using "
                "Community Dragon cost",
                unit.resolved_character_id,
                getattr(resolver, "set_number", None),
                unit.rarity,
                match_cost,
                static_cost,
            )
        return static_cost
    return match_cost


def item_identity(
    resolver: TFTNameResolver,
    api_name: str,
) -> tuple[str, str, str]:
    """Resolve one completed item to canonical API, display, and family values.

    Args:
        resolver: Community Dragon resolver for the match's TFT set.
        api_name: Item identifier supplied by the Riot match payload.

    Returns:
        Canonical API name, display name, and persisted item-type value.
    """
    resolve_api_name = getattr(resolver, "item_api_name", None)
    canonical_api_name = (
        resolve_api_name(api_name) if callable(resolve_api_name) else None
    ) or api_name
    display_name = _display_name(resolver, api_name, kind="item")
    classify_item = getattr(resolver, "classify_item", None)
    item_type = (
        classify_item(canonical_api_name)
        if callable(classify_item)
        else classify_item_name(canonical_api_name)
    )
    return (
        canonical_api_name,
        display_name,
        str(item_type or ItemTypes.UNKNOWN),
    )


def persist_item_metadata(
    session: Session,
    *,
    patch: str,
    tft_set_number: int,
    item_api_name: str,
    item_name: str,
    item_type: str,
) -> ItemMetadata:
    """Persist or validate canonical metadata observed during match ingestion.

    Args:
        session: Transaction owning the match insertion.
        patch: Normalized TFT patch represented by the match.
        tft_set_number: TFT set represented by the match.
        item_api_name: Canonical Community Dragon item identifier.
        item_name: Resolved player-facing item name.
        item_type: Classified item-family value.

    Returns:
        The existing or newly staged metadata row.

    Raises:
        ValueError: If the same patch/set/API identity has conflicting metadata.
    """
    identity = (patch, tft_set_number, item_api_name)
    existing = session.get(ItemMetadata, identity)
    if existing is None:
        existing = ItemMetadata(
            patch=patch,
            tft_set_number=tft_set_number,
            item_api_name=item_api_name,
            item_name=item_name,
            item_type=item_type,
        )
        session.add(existing)
        return existing
    if (existing.item_name, existing.item_type) != (item_name, item_type):
        raise ValueError(
            "Conflicting item metadata for "
            f"patch={patch!r}, set={tft_set_number}, api_name={item_api_name!r}: "
            f"stored={(existing.item_name, existing.item_type)!r}, "
            f"observed={(item_name, item_type)!r}"
        )
    return existing


def insert_match_payload(
    session: Session,
    payload: dict[str, Any],
    *,
    region: str,
    platform: str | None = None,
    resolver: TFTNameResolver | None = None,
    patch_override: str | None = None,
    commit: bool = True,
) -> bool:
    """Persist one Riot TFT match as ``match -> board -> unit/item/trait``.

    With ``commit=False`` the rows are only flushed, letting callers batch
    several matches per transaction (each commit is a round trip plus a WAL
    flush, which dominates ingest time against a remote database). When set,
    ``patch_override`` replaces the normalized patch derived from Riot's
    ``game_version`` while preserving that original API field.
    """

    match = RiotMatch.model_validate(payload)
    match_id = match.match_id()
    if not match_id:
        raise ValueError("Match payload has no match_id")

    existing = session.get(RawMatch, match_id)
    if existing is not None:
        return False

    info = match.info
    patch = patch_override or extract_patch(info.game_version)
    set_number = info.tft_set_number
    if set_number is None:
        set_number = load_config().chat.set_number
    resolver = resolver or _get_resolver(patch, set_number)
    raw_match = RawMatch(
        match_id=match_id,
        region=region,
        platform=platform,
        data_version=match.metadata.data_version,
        game_datetime=info.game_datetime,
        game_creation=info.game_creation,
        game_length=info.game_length,
        game_version=info.game_version,
        patch=patch,
        game_id=info.game_id,
        queue_id=info.queue_id or info.queueId or 0,
        map_id=info.map_id,
        tft_set_number=info.tft_set_number,
        tft_set_core_name=info.tft_set_core_name,
        tft_game_type=info.tft_game_type,
        game_variation=info.game_variation,
        end_of_game_result=info.end_of_game_result,
        ingested_at=int(time.time() * 1000),
    )
    for participant in info.participants:
        if participant.puuid == "BOT":
            # Riot gives every bot participant the literal puuid "BOT" with no
            # per-bot identifier, so multiple bots in one lobby collide on
            # (match_id, puuid) -- skip them rather than store unkeyable rows.
            continue
        units = [
            (
                idx,
                unit,
                _display_name(
                    resolver,
                    unit.resolved_character_id,
                    kind="unit",
                ),
            )
            for idx, unit in enumerate(participant.units)
            if unit.resolved_character_id
        ]
        companion = participant.companion
        board = PlayerBoard(
            puuid=participant.puuid,
            riot_id_game_name=participant.riot_id_game_name,
            riot_id_tagline=participant.riot_id_tagline,
            placement=participant.placement,
            level=participant.level,
            last_round=participant.last_round,
            players_eliminated=participant.players_eliminated,
            total_damage_to_players=participant.total_damage_to_players,
            gold_left=participant.gold_left,
            time_eliminated=participant.time_eliminated,
            win=participant.win,
            partner_group_id=participant.partner_group_id,
            companion_content_id=companion.content_ID if companion else None,
            companion_item_id=companion.item_ID if companion else None,
            companion_skin_id=companion.skin_ID if companion else None,
            companion_species=companion.species if companion else None,
        )
        raw_match.boards.append(board)

        # Retain every named trait state.  Analytics decides which rows are
        # active from style/tier_current rather than losing inactive raw data.
        traits_by_name: dict[str, BoardTrait] = {}
        for trait in participant.traits:
            if not trait.name:
                continue
            name = _trait_name(resolver, trait.name)
            traits_by_name[name] = BoardTrait(
                trait_name=name,
                num_units=trait.num_units,
                style=trait.style,
                tier_current=trait.tier_current,
                tier_total=trait.tier_total,
            )
        board.trait_rows.extend(traits_by_name.values())

        for unit_idx, unit, name in units:
            items = [
                item_identity(resolver, item_name)
                for item_name in unit.itemNames
                if not is_component_item(item_name)
            ][:3]
            for item_api_name, item_name, item_type in items:
                persist_item_metadata(
                    session,
                    patch=raw_match.patch or "unknown",
                    tft_set_number=int(raw_match.tft_set_number or 0),
                    item_api_name=item_api_name,
                    item_name=item_name,
                    item_type=item_type,
                )
            board_unit = BoardUnit(
                unit_name=name,
                unit_idx=unit_idx,
                star_level=unit.tier,
                cost=resolve_unit_cost(resolver, unit),
            )
            board.units.append(board_unit)
            board_unit.items.extend(
                UnitItem(
                    item_slot=item_slot,
                    item_api_name=item_api_name,
                    item_name=item_name,
                )
                for item_slot, (item_api_name, item_name, _item_type) in enumerate(items)
            )

    session.add(raw_match)
    if commit:
        session.commit()
    else:
        session.flush()
    return True


__all__ = [
    "insert_match_payload",
    "item_identity",
    "persist_item_metadata",
    "resolve_unit_cost",
    "get_patch_resolver",
]
