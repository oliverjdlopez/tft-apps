"""Backfill canonical item metadata and invalidate disposable analytics.

This maintenance command upgrades an existing relational database after item
identity and family metadata were added. It fetches Community Dragon once per
represented patch/set pair, backfills raw item API identities, persists the
classification snapshot, and clears derived analytics so the normal rebuild
path can recreate schema-versioned facts and aggregates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Callable, Iterator
from typing import Any

from sqlalchemy import inspect, select, text, tuple_
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session, sessionmaker

from constants import ItemTypes
from db.models import (
    AnalysisBoardItem,
    ItemMetadata,
    ItemStatQueryTable,
    RawMatch,
    UnitItem,
)
from db.session import engine_for, resolve_database_target
from utils.tft import TFTNameResolver

logger = logging.getLogger("tft-migrate-item-metadata")

ResolverFactory = Callable[[str, int], TFTNameResolver]
DEFAULT_BATCH_SIZE = 10_000
PROGRESS_LOG_ROWS = 1_000_000
_METADATA_COLUMNS = {
    "patch",
    "tft_set_number",
    "item_api_name",
    "item_name",
    "item_type",
}


def iter_item_row_batches(
    session: Session,
    *,
    batch_size: int,
) -> Iterator[list[RowMapping]]:
    """Yield raw item rows in bounded, restart-safe primary-key pages.

    Keyset pagination avoids retaining the full raw item table in memory and
    remains stable across the commits performed after each migration batch.

    Args:
        session: Maintenance session used to read normalized item rows.
        batch_size: Maximum number of item rows yielded at once.

    Yields:
        Ordered batches containing raw item identity and scope fields.

    Raises:
        ValueError: If ``batch_size`` is not positive.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    cursor_columns = (
        UnitItem.match_id,
        UnitItem.puuid,
        UnitItem.unit_idx,
        UnitItem.item_slot,
    )
    last_key: tuple[str, str, int, int] | None = None
    while True:
        statement = (
            select(
                UnitItem.match_id,
                UnitItem.puuid,
                UnitItem.unit_idx,
                UnitItem.item_slot,
                UnitItem.item_name,
                UnitItem.item_api_name,
                RawMatch.patch,
                RawMatch.tft_set_number,
            )
            .join(RawMatch, RawMatch.match_id == UnitItem.match_id)
            .order_by(*cursor_columns)
            .limit(batch_size)
        )
        if last_key is not None:
            statement = statement.where(
                tuple_(*cursor_columns) > tuple_(*last_key)
            )
        rows = list(session.execute(statement).mappings())
        if not rows:
            return
        yield rows
        final = rows[-1]
        last_key = (
            str(final["match_id"]),
            str(final["puuid"]),
            int(final["unit_idx"]),
            int(final["item_slot"]),
        )


def fetch_patch_resolver(patch: str, tft_set_number: int) -> TFTNameResolver:
    """Fetch the exact Community Dragon resolver used for one metadata snapshot.

    Args:
        patch: Normalized TFT patch stored on raw matches.
        tft_set_number: TFT set represented by those matches.

    Returns:
        A resolver backed by the requested patch's Community Dragon payload.
    """
    return asyncio.run(
        TFTNameResolver.from_latest(set_number=tft_set_number, patch=patch)
    )


def _add_column_if_missing(
    session: Session,
    table_name: str,
    column_name: str,
    sql_type: str,
) -> bool:
    """Add one nullable transition column when an existing schema lacks it.

    Args:
        session: Maintenance transaction.
        table_name: Existing table to inspect and alter.
        column_name: Column introduced by this migration.
        sql_type: Portable SQL type declaration for the new column.

    Returns:
        Whether the column was added.
    """
    inspector = inspect(session.connection())
    if not inspector.has_table(table_name):
        return False
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return False
    session.execute(
        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}")
    )
    return True


def _validate_existing_metadata_shape(session: Session) -> bool:
    """Reject an unsafe, structurally partial metadata table.

    Args:
        session: Maintenance transaction used for schema inspection.

    Returns:
        Whether the metadata table already existed.

    Raises:
        RuntimeError: If the existing table is missing required columns.
    """
    inspector = inspect(session.connection())
    if not inspector.has_table(ItemMetadata.__tablename__):
        return False
    columns = {
        column["name"]
        for column in inspector.get_columns(ItemMetadata.__tablename__)
    }
    missing = sorted(_METADATA_COLUMNS - columns)
    if missing:
        raise RuntimeError(
            "partially migrated item_metadata table is missing columns: "
            + ", ".join(missing)
        )
    return True


def _derived_item_metadata_is_partial(session: Session) -> bool:
    """Return whether disposable item facts contain transition nulls.

    Args:
        session: Maintenance transaction used to inspect derived tables.

    Returns:
        Whether an existing derived row requires a full rebuild.
    """
    inspector = inspect(session.connection())
    checks = (
        ("analysis_board_items", ("item_api_name",)),
        ("item_stats", ("item_api_name", "item_type")),
    )
    for table_name, columns in checks:
        if not inspector.has_table(table_name):
            continue
        present = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        if not set(columns).issubset(present):
            return True
        condition = " OR ".join(f"{column} IS NULL" for column in columns)
        if int(session.scalar(text(f"SELECT COUNT(*) FROM {table_name} WHERE {condition}")) or 0):
            return True
    return False


def _clear_derived_analytics(session: Session) -> None:
    """Clear rebuildable facts, aggregates, ledgers, and publication state.

    Args:
        session: Maintenance transaction whose raw item metadata was upgraded.
    """
    inspector = inspect(session.connection())
    tables = (
        "analysis_board_items",
        "analysis_board_traits",
        "analysis_board_units",
        "analysis_board_trait_lists",
        "analysis_board_unit_lists",
        "analysis_boards",
        "unit_loadout_stats",
        "item_stats",
        "unit_stats",
        "trait_stats",
        "analysis_processed_matches",
        "analysis_fact_builds",
        "matches",
    )
    for table_name in tables:
        if inspector.has_table(table_name):
            session.execute(text(f"DELETE FROM {table_name}"))
    if inspector.has_table("analysis_scopes"):
        session.execute(
            text(
                "UPDATE analysis_scopes SET status = 'pending', universe_boards = 0, "
                "last_success_at = NULL, last_error_at = NULL, last_error_details = NULL"
            )
        )


def migrate_item_metadata(
    session: Session,
    *,
    resolver_factory: ResolverFactory = fetch_patch_resolver,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, Any]:
    """Upgrade item identity storage and backfill metadata from exact patches.

    Args:
        session: Maintenance session for the target database.
        resolver_factory: Injectable exact-patch resolver factory used by tests.
        batch_size: Maximum raw item rows processed and committed together.

    Returns:
        Schema, backfill, unresolved, and analytics-invalidation counts.

    Raises:
        ValueError: If ``batch_size`` is not positive.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    metadata_table_existed = _validate_existing_metadata_shape(session)
    ItemMetadata.__table__.create(session.connection(), checkfirst=True)
    schema_changes = [
        changed
        for changed in (
            _add_column_if_missing(session, "unit_items", "item_api_name", "VARCHAR"),
            _add_column_if_missing(
                session, "analysis_board_items", "item_api_name", "VARCHAR"
            ),
            _add_column_if_missing(session, "item_stats", "item_api_name", "VARCHAR"),
            _add_column_if_missing(session, "item_stats", "item_type", "VARCHAR(32)"),
        )
        if changed
    ]
    session.commit()

    inspector = inspect(session.connection())
    has_raw_items = inspector.has_table("unit_items") and inspector.has_table(
        "raw_matches"
    )
    existing_metadata = {
        (str(row.patch), int(row.tft_set_number), str(row.item_api_name)): (
            str(row.item_name),
            str(row.item_type),
        )
        for row in session.execute(
            select(
                ItemMetadata.item_api_name,
                ItemMetadata.patch,
                ItemMetadata.tft_set_number,
                ItemMetadata.item_name,
                ItemMetadata.item_type,
            )
        )
    }
    resolvers: dict[tuple[str, int], TFTNameResolver] = {}
    resolved_items: dict[tuple[str, int, str], tuple[str, str, bool]] = {}
    backfilled = 0
    metadata_created = 0
    unresolved = 0
    derived_partial = _derived_item_metadata_is_partial(session)
    analytics_cleared = bool(schema_changes or derived_partial)
    if analytics_cleared:
        _clear_derived_analytics(session)
        session.commit()

    raw_rows = 0
    next_progress_log = PROGRESS_LOG_ROWS
    batches = (
        iter_item_row_batches(session, batch_size=batch_size)
        if has_raw_items
        else ()
    )
    for batch_number, rows in enumerate(batches, start=1):
        updates: list[dict[str, Any]] = []
        new_metadata: list[dict[str, Any]] = []
        for row in rows:
            raw_rows += 1
            patch = str(row["patch"] or "unknown")
            set_number = int(row["tft_set_number"] or 0)
            resolver = resolvers.get((patch, set_number))
            if resolver is None:
                resolver = resolver_factory(patch, set_number)
                resolvers[(patch, set_number)] = resolver
            stored_name = str(row["item_name"])
            resolution_key = (patch, set_number, stored_name)
            resolved = resolved_items.get(resolution_key)
            if resolved is None:
                api_name = resolver.item_api_name(stored_name) or stored_name
                item_type = str(
                    resolver.classify_item(api_name) or ItemTypes.UNKNOWN
                )
                is_resolved = (
                    resolver.item(stored_name) is not None
                    and item_type != ItemTypes.UNKNOWN
                )
                resolved = (api_name, item_type, is_resolved)
                resolved_items[resolution_key] = resolved
            api_name, item_type, is_resolved = resolved
            if not is_resolved:
                unresolved += 1
            if row["item_api_name"] != api_name:
                updates.append(
                    {
                        "item_api_name": api_name,
                        "match_id": row["match_id"],
                        "puuid": row["puuid"],
                        "unit_idx": row["unit_idx"],
                        "item_slot": row["item_slot"],
                    }
                )
            identity = (patch, set_number, api_name)
            values = (stored_name, item_type)
            existing_values = existing_metadata.get(identity)
            if existing_values is None:
                new_metadata.append(
                    {
                        "patch": patch,
                        "tft_set_number": set_number,
                        "item_api_name": api_name,
                        "item_name": stored_name,
                        "item_type": item_type,
                    }
                )
                existing_metadata[identity] = values
            elif existing_values != values:
                raise RuntimeError(
                    f"Conflicting item metadata for {identity!r}: "
                    f"stored={existing_values!r}, resolved={values!r}"
                )

        if (updates or new_metadata) and not analytics_cleared:
            # Invalidate published projections in the same transaction as the
            # first raw mutation so an interrupted migration remains safe.
            _clear_derived_analytics(session)
            analytics_cleared = True
        if updates:
            session.execute(
                text(
                    "UPDATE unit_items SET item_api_name = :item_api_name "
                    "WHERE match_id = :match_id AND puuid = :puuid "
                    "AND unit_idx = :unit_idx AND item_slot = :item_slot"
                ),
                updates,
            )
            backfilled += len(updates)
        if new_metadata:
            session.execute(ItemMetadata.__table__.insert(), new_metadata)
            metadata_created += len(new_metadata)
        session.commit()
        if raw_rows >= next_progress_log:
            logger.info(
                "item metadata migration progress batch=%s processed_rows=%s "
                "backfilled=%s metadata_rows=%s",
                batch_number,
                raw_rows,
                backfilled,
                metadata_created,
            )
            while next_progress_log <= raw_rows:
                next_progress_log += PROGRESS_LOG_ROWS

    if session.get_bind().dialect.name == "postgresql":
        for table_name, column_name in (
            (UnitItem.__tablename__, "item_api_name"),
            (AnalysisBoardItem.__tablename__, "item_api_name"),
            (ItemStatQueryTable.__tablename__, "item_api_name"),
            (ItemStatQueryTable.__tablename__, "item_type"),
        ):
            if inspect(session.connection()).has_table(table_name):
                session.execute(
                    text(
                        f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL"
                    )
                )
    for model in (ItemMetadata, UnitItem, AnalysisBoardItem, ItemStatQueryTable):
        if inspect(session.connection()).has_table(model.__tablename__):
            for index in model.__table__.indexes:
                index.create(session.connection(), checkfirst=True)
    session.commit()
    changed = analytics_cleared
    result = {
        "initial_state": (
            "empty"
            if not raw_rows
            else "partial"
            if schema_changes or backfilled or metadata_created or derived_partial
            else "current"
        ),
        "metadata_table_created": not metadata_table_existed,
        "schema_columns_added": len(schema_changes),
        "raw_items_backfilled": backfilled,
        "metadata_rows_created": metadata_created,
        "unresolved_items": unresolved,
        "analytics_cleared": analytics_cleared,
        "requires_rebuild": changed,
    }
    logger.info("item metadata migration complete: %s", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the maintenance command parser.

    Returns:
        Argument parser for explicit app-target or DSN execution.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="Explicit PostgreSQL maintenance DSN")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Raw item rows committed per batch (default: %(default)s)",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the item metadata migration against the configured app database.

    Args:
        argv: Optional command-line arguments for tests and direct invocation.
    """
    logging.basicConfig(level=logging.INFO)
    args = build_parser().parse_args(argv)
    target = resolve_database_target("app", args.dsn)
    with sessionmaker(bind=engine_for(target), expire_on_commit=False)() as session:
        print(
            json.dumps(
                migrate_item_metadata(session, batch_size=args.batch_size),
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
