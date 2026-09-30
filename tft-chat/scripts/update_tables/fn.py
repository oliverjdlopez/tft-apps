"""Table-update functions for the ``update-tables`` script."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import and_, case, exists, func, inspect, select, text, update

from common.sql import quote_identifier
from core.config import load_config
from db.build_query_tables import mark_scopes_dirty_for_matches
from db.models import AllMatch, RawMatch, TABLE_MODELS
from utils.tft import TFTNameResolver

logger = logging.getLogger("tft-update-tables.fn")

# Unit/item apiName-valued columns across the board tables and query tables.
# ``unit_name``/``item_name`` are resolved through TFTNameResolver.display_name.
_SIMPLE_NAME_COLUMNS = (
    "unit_name",
    "item_name",
    "item1",
    "item2",
    "item3",
    "other_item1",
    "other_item2",
    "trait_name",
)

_FIELD_RENAMES: dict[str, dict[str, str]] = {
    "player_units": {"name": "unit_name"},
    "player_items": {"name": "item_name", "holder": "unit_name"},
    "unit_stats": {"name": "unit_name"},
    "item_stats": {"name": "item_name", "holder": "unit_name"},
}

_resolvers: dict[int | None, TFTNameResolver] = {}
_name_cache: dict[tuple[int | None, str], str] = {}
_trait_cache: dict[tuple[int | None, str], str] = {}
_comp_code_cache: dict[tuple[int | None, str], str] = {}
_traits_code_cache: dict[tuple[int | None, str], str] = {}


def _get_resolver(set_number: int | None) -> TFTNameResolver:
    """Get (and cache) the name resolver for *set_number*."""
    resolver = _resolvers.get(set_number)
    if resolver is None:
        resolver = asyncio.run(TFTNameResolver.from_latest(set_number=set_number))
        _resolvers[set_number] = resolver
    return resolver


def _display_name(resolver: TFTNameResolver, api_name: str | None) -> str | None:
    """Resolve one apiName to its display name, leaving unresolvable values as-is."""
    if not api_name:
        return api_name
    key = (resolver.set_number, api_name)
    cached = _name_cache.get(key)
    if cached is not None:
        return cached
    resolved = resolver.display_name(api_name) or api_name
    _name_cache[key] = resolved
    return resolved


def _trait_display_name(resolver: TFTNameResolver, api_name: str) -> str:
    key = (resolver.set_number, api_name)
    cached = _trait_cache.get(key)
    if cached is not None:
        return cached
    resolved = resolver.trait_name(api_name) or api_name
    _trait_cache[key] = resolved
    return resolved


def _display_comp_code(resolver: TFTNameResolver, comp_code: str | None) -> str | None:
    """Resolve each ``#``-joined unit apiName in a ``comp_code`` string."""
    if not comp_code:
        return comp_code
    key = (resolver.set_number, comp_code)
    cached = _comp_code_cache.get(key)
    if cached is not None:
        return cached
    resolved = "#".join(_display_name(resolver, name) for name in comp_code.split("#"))
    _comp_code_cache[key] = resolved
    return resolved


def _display_traits_code(resolver: TFTNameResolver, traits_code: str | None) -> str | None:
    """Resolve each ``name_tier`` segment of a ``traits`` string to its trait name."""
    if not traits_code:
        return traits_code
    key = (resolver.set_number, traits_code)
    cached = _traits_code_cache.get(key)
    if cached is not None:
        return cached
    segments = []
    for segment in traits_code.split("#"):
        api_name, _, tier = segment.rpartition("_")
        if not api_name:
            segments.append(segment)
            continue
        segments.append(f"{_trait_display_name(resolver, api_name)}_{tier}")
    resolved = "#".join(segments)
    _traits_code_cache[key] = resolved
    return resolved


def _model_for_table(table: str) -> Any:
    model = TABLE_MODELS.get(table)
    if model is None:
        raise ValueError(
            f"Unknown table {table!r}. Choices: {', '.join(sorted(TABLE_MODELS))}"
        )
    return model


def _chunks(items: list[tuple[str, str]], size: int) -> list[list[tuple[str, str]]]:
    size = max(size, 1)
    return [items[i : i + size] for i in range(0, len(items), size)]


def _has_board_key(model: Any) -> bool:
    columns = model.__table__.columns
    return (
        "match_id" in columns
        and "puuid" in columns
        and model not in (AllMatch, RawMatch)
    )


def _normalized_board_model(model: Any) -> bool:
    return model.__tablename__ in {
        "player_boards",
        "board_units",
        "unit_items",
        "board_traits",
    }


def _match_join_clause(model: Any) -> Any:
    if _normalized_board_model(model):
        return RawMatch.match_id == model.match_id
    return and_(AllMatch.match_id == model.match_id, AllMatch.puuid == model.puuid)


def _match_set_column(model: Any) -> Any:
    return RawMatch.tft_set_number if _normalized_board_model(model) else AllMatch.tft_set_number


def _distinct_column_values(
    session: Any,
    model: Any,
    column_name: str,
) -> dict[int | None, set[str]]:
    column = getattr(model, column_name)
    set_column = getattr(model, "tft_set_number", None)
    values_by_set: dict[int | None, set[str]] = {}

    if set_column is not None:
        stmt = select(set_column, column).where(column.is_not(None)).distinct()
        for set_number, value in session.execute(stmt):
            if value:
                values_by_set.setdefault(set_number, set()).add(value)
        return values_by_set

    if _has_board_key(model):
        match_model = RawMatch if _normalized_board_model(model) else AllMatch
        stmt = (
            select(_match_set_column(model), column)
            .join(match_model, _match_join_clause(model))
            .where(column.is_not(None))
            .distinct()
        )
        for set_number, value in session.execute(stmt):
            if value:
                values_by_set.setdefault(set_number, set()).add(value)
        return values_by_set

    stmt = select(column).where(column.is_not(None)).distinct()
    values_by_set[None] = {value for (value,) in session.execute(stmt) if value}
    return values_by_set


def _resolve_column_mapping(
    values_by_set: dict[int | None, set[str]],
    resolver_fn: Any,
) -> dict[int | None, dict[str, str]]:
    mappings: dict[int | None, dict[str, str]] = {}
    for set_number, values in values_by_set.items():
        effective_set = set_number
        if effective_set is None:
            effective_set = load_config().chat.set_number
        resolver = _get_resolver(effective_set)
        mapping = {
            value: resolved
            for value in values
            if (resolved := resolver_fn(resolver, value)) != value
        }
        if mapping:
            mappings[set_number] = mapping
    return mappings


def _set_filter(model: Any, set_number: int | None) -> Any | None:
    set_column = getattr(model, "tft_set_number", None)
    if set_column is not None:
        if set_number is None:
            return set_column.is_(None)
        return set_column == set_number
    if not _has_board_key(model):
        return None

    set_column = _match_set_column(model)
    match_set_clause = (
        set_column.is_(None)
        if set_number is None
        else set_column == set_number
    )
    return exists().where(and_(_match_join_clause(model), match_set_clause))


def _apply_column_mappings(
    session: Any,
    model: Any,
    column_name: str,
    mappings_by_set: dict[int | None, dict[str, str]],
    *,
    batch_size: int,
) -> int:
    column = getattr(model, column_name)
    changed = 0

    for set_number, mapping in mappings_by_set.items():
        for chunk in _chunks(list(mapping.items()), batch_size):
            chunk_mapping = dict(chunk)
            affected_match_ids: list[str] = []
            if _normalized_board_model(model):
                affected_match_ids = list(
                    session.scalars(
                        select(model.match_id)
                        .where(column.in_(chunk_mapping.keys()))
                        .distinct()
                    )
                )
            stmt = (
                update(model)
                .where(column.in_(chunk_mapping.keys()))
                .values({column_name: case(chunk_mapping, value=column, else_=column)})
                .execution_options(synchronize_session=False)
            )
            set_clause = _set_filter(model, set_number)
            if set_clause is not None:
                stmt = stmt.where(set_clause)
            result = session.execute(stmt)
            if affected_match_ids and (result.rowcount or 0) > 0:
                mark_scopes_dirty_for_matches(
                    session,
                    affected_match_ids,
                    reason=f"{model.__tablename__}.{column_name} names were updated",
                )
            session.commit()
            changed += max(result.rowcount or 0, 0)

    return changed


def _log_mappings(
    table: str,
    column_name: str,
    mappings_by_set: dict[int | None, dict[str, str]],
) -> None:
    """Log every value mapping used for a table column."""
    for set_number, mapping in sorted(
        mappings_by_set.items(), key=lambda item: (-1 if item[0] is None else item[0])
    ):
        for original, resolved in sorted(mapping.items()):
            logger.info(
                "table=%s column=%s set=%s mapping=%r -> %r",
                table,
                column_name,
                set_number,
                original,
                resolved,
            )


def dientity(session: Any, table: str, *, batch_size: int = 2000) -> int:
    """No-op table updater that returns the table's row count."""
    del batch_size
    model = _model_for_table(table)
    return int(session.query(func.count()).select_from(model).scalar() or 0)


def rename_field_names(session: Any, table: str, *, batch_size: int = 2000) -> int:
    """Rename ambiguous DB columns to semantic field names.

    Examples:
    - player_units.name -> player_units.unit_name
    - player_items.name -> player_items.item_name
    - player_items.holder -> player_items.unit_name
    - unit_stats.name -> unit_stats.unit_name
    - item_stats.name/holder -> item_stats.item_name/unit_name
    """
    del batch_size
    _model_for_table(table)
    renames = _FIELD_RENAMES.get(table, {})
    if not renames:
        logger.info("table=%s has no field-name renames", table)
        return 0

    existing_columns = {
        column["name"] for column in inspect(session.bind).get_columns(table)
    }
    changed = 0
    for old_name, new_name in renames.items():
        if new_name in existing_columns:
            logger.info(
                "table=%s column=%s already exists; skipping rename from %s",
                table,
                new_name,
                old_name,
            )
            continue
        if old_name not in existing_columns:
            logger.info(
                "table=%s column=%s missing; skipping rename to %s",
                table,
                old_name,
                new_name,
            )
            continue

        session.execute(
            text(
                "ALTER TABLE "
                f"{quote_identifier(table)} RENAME COLUMN "
                f"{quote_identifier(old_name)} TO {quote_identifier(new_name)}"
            )
        )
        session.commit()
        existing_columns.remove(old_name)
        existing_columns.add(new_name)
        changed += 1
        logger.info("table=%s renamed column %s -> %s", table, old_name, new_name)

    return changed


def resolve_names(session: Any, table: str, *, batch_size: int = 2000) -> int:
    """Replace unit/trait/item apiNames in one table with display names.

    Covers the apiName-valued columns on ``player_board``, ``player_units``,
    ``player_items``, ``unit_stats``, and ``item_stats``: ``unit_name``/
    ``item_name``/``item*``/``other_item*`` hold bare apiNames (``TFT15_Ashe``,
    ``TFT_Item_InfinityEdge``) and are resolved directly, while
    ``player_board``'s ``comp_code`` and ``traits`` columns pack several
    apiNames into one ``#``-delimited string and are resolved piece by piece
    so the delimiters survive. Columns not present on a given row, and values
    that don't resolve to a known apiName, pass through unchanged.
    """
    model = _model_for_table(table)
    rename_field_names(session, table)
    table_columns = {column.name for column in model.__table__.columns}
    changed = 0

    column_resolvers = {
        **{
            column_name: _display_name
            for column_name in _SIMPLE_NAME_COLUMNS
            if column_name in table_columns
        },
        **({"comp_code": _display_comp_code} if "comp_code" in table_columns else {}),
        **({"traits": _display_traits_code} if "traits" in table_columns else {}),
        **(
            {"trait_name": _trait_display_name}
            if "trait_name" in table_columns
            else {}
        ),
    }

    if not column_resolvers:
        logger.info("table=%s has no name columns to resolve", table)
        return 0

    for column_name, resolver_fn in column_resolvers.items():
        values_by_set = _distinct_column_values(session, model, column_name)
        mappings_by_set = _resolve_column_mapping(values_by_set, resolver_fn)
        _log_mappings(table, column_name, mappings_by_set)
        column_changed = _apply_column_mappings(
            session,
            model,
            column_name,
            mappings_by_set,
            batch_size=batch_size,
        )
        changed += column_changed
        logger.info(
            "table=%s column=%s mapped_values=%d changed_rows=%d",
            table,
            column_name,
            sum(len(mapping) for mapping in mappings_by_set.values()),
            column_changed,
        )

    logger.info("table=%s resolve_names changed_rows=%d", table, changed)
    return changed
