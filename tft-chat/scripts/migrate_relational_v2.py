"""Maintenance-window migration from supported legacy stores to relational v2.

Operational prerequisites (service stop and RDS snapshot) are intentionally
external.  This command performs an idempotent, read-only preflight before any
cutover DDL, aborts on nondeterministic conflicts, backfills in match batches,
validates the relational graph, builds every represented analysis scope through
the runtime incremental processor, and retains source tables with ``_legacy``
suffixes for one release.  It accepts both the packed ``all_matches``/``player_*``
store and the earlier normalized ``matches``/``participant_*`` store.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import logging
import time
from typing import Any, Callable, Sequence

from sqlalchemy import MetaData, Table, and_, case, func, inspect, or_, select, text
from sqlalchemy.orm import Session, sessionmaker

from common.sql import quote_identifier
from core.config import load_config
from db.build_query_tables import (
    _replace_match_projection,
    configured_queue_id,
    finalize_query_tables,
    process_match_batch,
    resolve_analysis_scope,
)
from db.insert import get_patch_resolver
from db.models import (
    ANALYSIS_MODELS,
    AnalysisProcessedMatch,
    AnalysisScope,
    Base,
    BoardTrait,
    BoardUnit,
    PlayerBoard,
    RAW_GRAPH_MODELS,
    RUNTIME_MODELS,
    RawMatch,
    UnitItem,
)
from db.session import engine_for, resolve_database_target
from db.utils import extract_patch
from db.validation import validate_relational_v2


logger = logging.getLogger("tft-migrate-relational-v2")
PREFLIGHT_PROGRESS_ROWS = 10_000
AGGREGATE_NAMES = (
    "unit_stats",
    "item_stats",
    "trait_stats",
    "unit_loadout_stats",
)
StaticResolverFactory = Callable[[str, int | None], Any]


class MigrationConflictError(RuntimeError):
    """Raised before cutover when legacy rows cannot be mapped deterministically."""


@dataclass(frozen=True)
class MigrationSources:
    """Reflected source graph for one supported pre-v2 schema."""

    kind: str
    match_metadata: Table
    participants: Table
    units: Table | None
    items: Table | None
    traits: Table | None
    packed_boards: Table | None
    raw_tables: tuple[Table, ...]


def _source_name(session: Session, base: str) -> str | None:
    inspector = inspect(session.connection())
    for candidate in (base, f"{base}_legacy"):
        if inspector.has_table(candidate):
            return candidate
    return None


def _reflect(session: Session, base: str, *, required: bool = False) -> Table | None:
    name = _source_name(session, base)
    if name is None:
        if required:
            raise RuntimeError(f"legacy source table {base!r} is missing")
        return None
    return Table(name, MetaData(), autoload_with=session.connection())


def _reflect_matching(
    session: Session,
    base: str,
    *,
    required_columns: Sequence[str],
    forbidden_columns: Sequence[str] = (),
) -> Table | None:
    inspector = inspect(session.connection())
    for name in (base, f"{base}_legacy"):
        if not inspector.has_table(name):
            continue
        columns = {column["name"] for column in inspector.get_columns(name)}
        if all(column in columns for column in required_columns) and not any(
            column in columns for column in forbidden_columns
        ):
            return Table(name, MetaData(), autoload_with=session.connection())
    return None


def _migration_sources(session: Session) -> MigrationSources:
    all_matches = _reflect(session, "all_matches")
    if all_matches is not None:
        player_board = _reflect(session, "player_board")
        player_units = _reflect(session, "player_units")
        player_items = _reflect(session, "player_items")
        raw_tables = tuple(
            table
            for table in (all_matches, player_board, player_units, player_items)
            if table is not None
        )
        return MigrationSources(
            kind="packed_v1",
            match_metadata=all_matches,
            participants=all_matches,
            units=player_units,
            items=player_items,
            traits=None,
            packed_boards=player_board,
            raw_tables=raw_tables,
        )

    # The earlier normalized store used one metadata row in ``matches`` and
    # separate participant/unit/item/trait tables.  A relational-v2 rerun may
    # find its retained metadata source as ``matches_legacy`` while the new
    # compatibility projection occupies ``matches``.
    matches = _reflect_matching(
        session,
        "matches",
        required_columns=("match_id", "patch", "queue_id"),
        forbidden_columns=("puuid",),
    )
    if matches is not None:
        required: dict[str, tuple[str, ...]] = {
            "participants": ("match_id", "puuid", "placement"),
            "participant_units": (
                "match_id",
                "puuid",
                "unit_index",
                "character_id",
                "tier",
            ),
            "participant_unit_items": (
                "match_id",
                "puuid",
                "unit_index",
                "item_index",
                "character_id",
                "item_name",
            ),
            "participant_traits": (
                "match_id",
                "puuid",
                "trait_name",
                "tier_current",
            ),
        }
        reflected: dict[str, Table] = {}
        missing: list[str] = []
        for name, columns in required.items():
            table = _reflect_matching(
                session,
                name,
                required_columns=columns,
            )
            if table is None:
                missing.append(name)
            else:
                reflected[name] = table
        if missing:
            raise RuntimeError(
                "normalized legacy source is incomplete; missing tables: "
                + ", ".join(repr(name) for name in missing)
            )
        raw_tables = (
            matches,
            reflected["participants"],
            reflected["participant_units"],
            reflected["participant_unit_items"],
            reflected["participant_traits"],
        )
        return MigrationSources(
            kind="normalized_v1",
            match_metadata=matches,
            participants=reflected["participants"],
            units=reflected["participant_units"],
            items=reflected["participant_unit_items"],
            traits=reflected["participant_traits"],
            packed_boards=None,
            raw_tables=raw_tables,
        )

    raise RuntimeError(
        "no supported legacy source schema was found; expected "
        "'all_matches'/'all_matches_legacy' (packed v1) or a metadata-only "
        "'matches'/'matches_legacy' table with the participant_* tables "
        "(normalized v1)"
    )


def _count(session: Session, table: Table | type[Any]) -> int:
    source = table if isinstance(table, Table) else table.__table__
    return int(session.scalar(select(func.count()).select_from(source)) or 0)


def _column(table: Table, *names: str) -> Any | None:
    for name in names:
        if name in table.c:
            return table.c[name]
    return None


def parse_legacy_traits(code: str | None) -> tuple[list[tuple[str, int]], list[str]]:
    """Parse by the final underscore so names containing underscores survive."""
    parsed: list[tuple[str, int]] = []
    malformed: list[str] = []
    for segment in (code or "").split("#"):
        if not segment:
            continue
        name, separator, tier_text = segment.rpartition("_")
        if not separator or not name:
            malformed.append(segment)
            continue
        try:
            tier = int(tier_text)
        except ValueError:
            malformed.append(segment)
            continue
        parsed.append((name, tier))
    return parsed, malformed


def _duplicate_count(session: Session, table: Table | None, names: Sequence[str]) -> int:
    if table is None or not all(name in table.c for name in names):
        return 0
    columns = [table.c[name] for name in names]
    groups = (
        select(*columns, func.count().label("rows"))
        .select_from(table)
        .group_by(*columns)
        .having(func.count() > 1)
        .subquery()
    )
    return int(session.scalar(select(func.count()).select_from(groups)) or 0)


def migration_preflight(session: Session) -> dict[str, Any]:
    """Audit legacy determinism and shape without changing schema or data."""
    started = time.perf_counter()
    logger.info("preflight started")
    sources = _migration_sources(session)
    match_metadata = sources.match_metadata
    participants = sources.participants
    player_board = (
        sources.packed_boards
        if sources.kind == "packed_v1"
        else sources.participants
    )
    player_units = sources.units
    player_items = sources.items
    player_traits = sources.traits

    metadata_names = [
        name
        for name in (
            "region",
            "platform",
            "game_datetime",
            "game_length",
            "game_version",
            "patch",
            "queue_id",
            "tft_set_number",
            "tft_set_core_name",
        )
        if name in match_metadata.c
    ]
    conflicting_ids: list[str] = []
    conflict_count = 0
    match_count = 0
    current_match_id: str | None = None
    current_metadata: set[tuple[Any, ...]] = set()

    def finish_match() -> None:
        nonlocal conflict_count, match_count
        if current_match_id is None:
            return
        match_count += 1
        if len(current_metadata) > 1:
            conflict_count += 1
            if len(conflicting_ids) < 25:
                conflicting_ids.append(current_match_id)

    metadata_order = [match_metadata.c.match_id]
    if "puuid" in match_metadata.c:
        metadata_order.append(match_metadata.c.puuid)
    metadata_result = (
        session.execute(select(match_metadata).order_by(*metadata_order))
        .mappings()
        .yield_per(10_000)
    )
    metadata_rows = 0
    for row in metadata_result:
        metadata_rows += 1
        match_id = str(row["match_id"])
        if current_match_id is not None and match_id != current_match_id:
            finish_match()
            current_metadata.clear()
        current_match_id = match_id
        current_metadata.add(tuple(row[name] for name in metadata_names))
        if metadata_rows % PREFLIGHT_PROGRESS_ROWS == 0:
            logger.info(
                "preflight progress stage=match_metadata rows=%d matches=%d "
                "conflicts=%d elapsed_seconds=%.3f",
                metadata_rows,
                match_count,
                conflict_count,
                time.perf_counter() - started,
            )
    finish_match()
    logger.info(
        "preflight stage complete stage=match_metadata rows=%d matches=%d "
        "conflicts=%d elapsed_seconds=%.3f",
        metadata_rows,
        match_count,
        conflict_count,
        time.perf_counter() - started,
    )

    def orphan_keys(
        child: Table | None,
        parent: Table | None,
        names: Sequence[str],
    ) -> int:
        if child is None:
            return 0
        child_keys = tuple(child.c[name] for name in names)
        if parent is None:
            distinct_keys = select(*child_keys).distinct().subquery()
        else:
            distinct_keys = (
                select(*child_keys)
                .select_from(
                    child.outerjoin(
                        parent,
                        and_(*(parent.c[name] == child.c[name] for name in names)),
                    )
                )
                .where(parent.c[names[0]].is_(None))
                .distinct()
                .subquery()
            )
        return int(session.scalar(select(func.count()).select_from(distinct_keys)) or 0)

    malformed: Counter[str] = Counter()
    trait_rows = 0
    if player_board is not None and "traits" in player_board.c:
        for code in session.scalars(select(player_board.c.traits)):
            trait_rows += 1
            _parsed, bad = parse_legacy_traits(code)
            malformed.update(bad)
            if trait_rows % PREFLIGHT_PROGRESS_ROWS == 0:
                logger.info(
                    "preflight progress stage=packed_traits rows=%d "
                    "malformed_segments=%d elapsed_seconds=%.3f",
                    trait_rows,
                    sum(malformed.values()),
                    time.perf_counter() - started,
                )
    elif player_traits is not None:
        trait_rows = _count(session, player_traits)
    trait_stage = "packed_traits" if sources.kind == "packed_v1" else "normalized_traits"
    logger.info(
        "preflight stage complete stage=%s rows=%d "
        "malformed_segments=%d elapsed_seconds=%.3f",
        trait_stage,
        trait_rows,
        sum(malformed.values()),
        time.perf_counter() - started,
    )

    packed_item_instances = 0
    packed_item_board_count = 0
    unit_rows = 0
    if sources.kind == "packed_v1" and player_units is not None:
        item_columns = [
            player_units.c[name]
            for name in ("item1", "item2", "item3")
            if name in player_units.c
        ]
        previous_item_board: tuple[str, str] | None = None
        for row in session.execute(
            select(player_units.c.match_id, player_units.c.puuid, *item_columns)
            .order_by(player_units.c.match_id, player_units.c.puuid)
        ).yield_per(10_000):
            unit_rows += 1
            count = sum(value is not None and str(value) != "" for value in row[2:])
            packed_item_instances += count
            if count:
                board_key = (str(row.match_id), str(row.puuid))
                if board_key != previous_item_board:
                    packed_item_board_count += 1
                    previous_item_board = board_key
            if unit_rows % PREFLIGHT_PROGRESS_ROWS == 0:
                logger.info(
                    "preflight progress stage=packed_items rows=%d item_instances=%d "
                    "boards_with_items=%d elapsed_seconds=%.3f",
                    unit_rows,
                    packed_item_instances,
                    packed_item_board_count,
                    time.perf_counter() - started,
                )
    elif player_units is not None:
        unit_rows = _count(session, player_units)
        if player_items is not None:
            packed_item_instances = _count(session, player_items)
            item_boards = (
                select(player_items.c.match_id, player_items.c.puuid)
                .distinct()
                .subquery()
            )
            packed_item_board_count = int(
                session.scalar(select(func.count()).select_from(item_boards)) or 0
            )
    item_stage = "packed_items" if sources.kind == "packed_v1" else "normalized_items"
    logger.info(
        "preflight stage complete stage=%s rows=%d item_instances=%d "
        "boards_with_items=%d elapsed_seconds=%.3f",
        item_stage,
        unit_rows,
        packed_item_instances,
        packed_item_board_count,
        time.perf_counter() - started,
    )

    logger.info(
        "preflight stage started stage=integrity_checks elapsed_seconds=%.3f",
        time.perf_counter() - started,
    )
    duplicate_item_slot_keys = (
        _duplicate_count(
            session,
            player_items,
            ("match_id", "puuid", "unit_index", "item_index"),
        )
        if sources.kind == "normalized_v1"
        else 0
    )
    duplicate_trait_keys = (
        _duplicate_count(
            session,
            player_traits,
            ("match_id", "puuid", "trait_name"),
        )
        if sources.kind == "normalized_v1"
        else 0
    )
    ambiguous_unit_character_keys = (
        _duplicate_count(
            session,
            player_units,
            ("match_id", "puuid", "character_id"),
        )
        if sources.kind == "normalized_v1"
        else 0
    )
    invalid_item_slots = 0
    excess_item_capacity_groups = 0
    excess_item_rows = 0
    if (
        sources.kind == "normalized_v1"
        and player_items is not None
        and player_units is not None
        and "item_index" in player_items.c
    ):
        invalid_item_slots = int(
            session.scalar(
                select(func.count())
                .select_from(player_items)
                .where(
                    or_(
                        player_items.c.item_index < 0,
                        player_items.c.item_index > 2,
                    )
                )
            )
            or 0
        )
        unit_capacity = (
            select(
                player_units.c.match_id,
                player_units.c.puuid,
                player_units.c.character_id,
                (func.count() * 3).label("capacity"),
            )
            .group_by(
                player_units.c.match_id,
                player_units.c.puuid,
                player_units.c.character_id,
            )
            .subquery()
        )
        item_counts = (
            select(
                player_items.c.match_id,
                player_items.c.puuid,
                player_items.c.character_id,
                func.count().label("items"),
            )
            .group_by(
                player_items.c.match_id,
                player_items.c.puuid,
                player_items.c.character_id,
            )
            .subquery()
        )
        capacity_rows = (
            select(item_counts.c["items"], unit_capacity.c.capacity)
            .join(
                unit_capacity,
                and_(
                    unit_capacity.c.match_id == item_counts.c.match_id,
                    unit_capacity.c.puuid == item_counts.c.puuid,
                    unit_capacity.c.character_id == item_counts.c.character_id,
                ),
            )
            .subquery()
        )
        excess_item_capacity_groups = int(
            session.scalar(
                select(func.count())
                .select_from(capacity_rows)
                .where(capacity_rows.c["items"] > capacity_rows.c.capacity)
            )
            or 0
        )
        excess_item_rows = int(
            session.scalar(
                select(
                    func.sum(
                        case(
                            (
                                capacity_rows.c["items"] > capacity_rows.c.capacity,
                                capacity_rows.c["items"] - capacity_rows.c.capacity,
                            ),
                            else_=0,
                        )
                    )
                ).select_from(capacity_rows)
            )
            or 0
        )

    if sources.kind == "normalized_v1":
        orphan_report = {
            "participants_without_match": orphan_keys(
                participants, match_metadata, ("match_id",)
            ),
            "boards_without_participant": 0,
            "units_without_board": orphan_keys(
                player_units, participants, ("match_id", "puuid")
            ),
            "items_without_unit": orphan_keys(
                player_items,
                player_units,
                ("match_id", "puuid", "character_id"),
            ),
            "traits_without_board": orphan_keys(
                player_traits, participants, ("match_id", "puuid")
            ),
        }
    else:
        orphan_report = {
            "boards_without_participant": orphan_keys(
                player_board, participants, ("match_id", "puuid")
            ),
            "units_without_board": orphan_keys(
                player_units, player_board, ("match_id", "puuid")
            ),
            "items_without_board": orphan_keys(
                player_items, player_board, ("match_id", "puuid")
            ),
        }

    report = {
        "source_kind": sources.kind,
        "source_tables": {
            table.name: _count(session, table) for table in sources.raw_tables
        },
        "matches": match_count,
        "participants": _count(session, participants),
        "conflicting_match_metadata": conflict_count,
        "conflicting_match_ids_sample": conflicting_ids[:25],
        "duplicate_board_keys": _duplicate_count(
            session, player_board, ("match_id", "puuid")
        ),
        "duplicate_unit_index_keys": _duplicate_count(
            session,
            player_units,
            (
                "match_id",
                "puuid",
                "unit_index" if sources.kind == "normalized_v1" else "unit_idx",
            ),
        ),
        "duplicate_item_slot_keys": duplicate_item_slot_keys,
        "duplicate_trait_keys": duplicate_trait_keys,
        "ambiguous_unit_character_keys": ambiguous_unit_character_keys,
        "invalid_item_slots": invalid_item_slots,
        "orphans": orphan_report,
        "malformed_trait_segments": sum(malformed.values()),
        "malformed_trait_samples": [
            {"segment": segment, "rows": count}
            for segment, count in malformed.most_common(25)
        ],
        "item_representations": {
            "unit_item_column_instances": packed_item_instances,
            "unit_item_column_boards": packed_item_board_count,
            "ambiguous_player_item_rows": (
                _count(session, player_items)
                if sources.kind == "packed_v1" and player_items is not None
                else 0
            ),
            "normalized_item_rows": (
                packed_item_instances if sources.kind == "normalized_v1" else 0
            ),
            "groups_over_three_per_unit_capacity": excess_item_capacity_groups,
            "excess_rows_over_three_per_unit_capacity": excess_item_rows,
        },
    }
    nondeterministic = (
        report["conflicting_match_metadata"]
        + report["duplicate_board_keys"]
        + report["duplicate_trait_keys"]
        + (
            report["duplicate_unit_index_keys"]
            if sources.kind == "packed_v1"
            else 0
        )
    )
    report["nondeterministic_conflicts"] = nondeterministic
    logger.info(
        "preflight stage complete stage=integrity_checks "
        "nondeterministic_conflicts=%d elapsed_seconds=%.3f",
        nondeterministic,
        time.perf_counter() - started,
    )
    logger.info(
        "preflight complete matches=%d participants=%d nondeterministic_conflicts=%d "
        "elapsed_seconds=%.3f",
        report["matches"],
        report["participants"],
        nondeterministic,
        time.perf_counter() - started,
    )
    return report


def _assert_preflight_safe(report: dict[str, Any]) -> None:
    if report["nondeterministic_conflicts"]:
        raise MigrationConflictError(
            "Relational v2 preflight found nondeterministic metadata/board/unit/trait "
            f"conflicts; no cutover changes were made: {json.dumps(report, sort_keys=True)}"
        )


def _rename_table(session: Session, source: str, target: str) -> bool:
    inspector = inspect(session.connection())
    if not inspector.has_table(source):
        return False
    if inspector.has_table(target):
        return False
    session.execute(
        text(f"ALTER TABLE {quote_identifier(source)} RENAME TO {quote_identifier(target)}")
    )
    if session.get_bind().dialect.name == "postgresql":
        _rename_postgres_table_objects(session, source, target)
    return True


def _renamed_object_name(name: str, source: str, target: str) -> str:
    candidate = (
        target + name[len(source) :]
        if name.startswith(source)
        else f"{target}_{name}"
    )
    if len(candidate) <= 63:
        return candidate
    digest = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:8]
    return f"{candidate[:54]}_{digest}"


def _rename_postgres_table_objects(
    session: Session,
    source: str,
    target: str,
) -> None:
    """Free v2 constraint/index names retained by PostgreSQL table rename."""
    constraints = list(
        session.scalars(
            text(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE n.nspname = current_schema() AND t.relname = :table_name"
            ),
            {"table_name": target},
        )
    )
    for old_name in constraints:
        new_name = _renamed_object_name(str(old_name), source, target)
        if new_name == old_name:
            continue
        session.execute(
            text(
                f"ALTER TABLE {quote_identifier(target)} RENAME CONSTRAINT "
                f"{quote_identifier(str(old_name))} TO {quote_identifier(new_name)}"
            )
        )

    indexes = list(
        session.scalars(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = :table_name"
            ),
            {"table_name": target},
        )
    )
    for old_name in indexes:
        if str(old_name).startswith(target):
            continue
        new_name = _renamed_object_name(str(old_name), source, target)
        session.execute(
            text(
                f"ALTER INDEX {quote_identifier(str(old_name))} "
                f"RENAME TO {quote_identifier(new_name)}"
            )
        )


def _prepare_analysis_table_cutover(session: Session) -> list[str]:
    """Move pre-v2 same-name aggregate tables aside before v2 creation."""
    renamed: list[str] = []
    inspector = inspect(session.connection())
    for name in AGGREGATE_NAMES:
        if not inspector.has_table(name):
            continue
        columns = {column["name"] for column in inspector.get_columns(name)}
        if "scope_id" in columns:
            continue
        target = f"{name}_legacy"
        if inspector.has_table(target):
            raise MigrationConflictError(
                f"both stale {name!r} and retained {target!r} exist; resolve the "
                "partial cutover before rerunning"
            )
        if _rename_table(session, name, target):
            renamed.append(target)
            inspector = inspect(session.connection())
    session.commit()
    return renamed


def _prepare_runtime_table_cutover(session: Session) -> list[str]:
    """Retain pre-v2 tables whose names collide with relational-v2 tables."""
    renamed: list[str] = []
    inspector = inspect(session.connection())
    for model in RUNTIME_MODELS:
        name = model.__tablename__
        if not inspector.has_table(name):
            continue
        actual_columns = {
            column["name"] for column in inspector.get_columns(name)
        }
        expected_columns = {column.name for column in model.__table__.columns}
        actual_pk = set(
            inspector.get_pk_constraint(name).get("constrained_columns") or ()
        )
        expected_pk = {column.name for column in model.__table__.primary_key.columns}
        if expected_columns.issubset(actual_columns) and actual_pk == expected_pk:
            continue
        target = f"{name}_legacy"
        if inspector.has_table(target):
            raise MigrationConflictError(
                f"both incompatible {name!r} and retained {target!r} exist; "
                "resolve the partial cutover before rerunning"
            )
        if _rename_table(session, name, target):
            renamed.append(target)
            inspector = inspect(session.connection())
    session.commit()
    return renamed


def _create_v2_schema(session: Session) -> None:
    Base.metadata.create_all(
        bind=session.connection(),
        tables=[model.__table__ for model in RUNTIME_MODELS],
    )
    session.commit()


def _mapping_value(row: Any, name: str, default: Any = None) -> Any:
    return row[name] if name in row else default


def _source_match_id_page(
    session: Session,
    matches: Table,
    *,
    cursor: str | None,
    batch_size: int,
) -> list[str]:
    statement = select(matches.c.match_id).distinct()
    if cursor is not None:
        statement = statement.where(matches.c.match_id > cursor)
    return [
        str(value)
        for value in session.scalars(
            statement.order_by(matches.c.match_id).limit(max(int(batch_size), 1))
        )
    ]


def _raw_match_from_source(match_id: str, metadata: Any) -> RawMatch:
    version = str(_mapping_value(metadata, "game_version", ""))
    kwargs: dict[str, Any] = {
        "match_id": match_id,
        "region": str(_mapping_value(metadata, "region", "unknown")),
        "platform": _mapping_value(metadata, "platform"),
        "game_datetime": int(_mapping_value(metadata, "game_datetime", 0) or 0),
        "game_length": float(_mapping_value(metadata, "game_length", 0.0) or 0.0),
        "game_version": version,
        "patch": _mapping_value(metadata, "patch") or extract_patch(version),
        "queue_id": int(_mapping_value(metadata, "queue_id", 0) or 0),
        "tft_set_number": _mapping_value(metadata, "tft_set_number"),
        "tft_set_core_name": _mapping_value(metadata, "tft_set_core_name"),
        "ingested_at": int(_mapping_value(metadata, "ingested_at", 0) or 0),
    }
    for name in (
        "data_version",
        "game_creation",
        "game_id",
        "map_id",
        "tft_game_type",
        "game_variation",
        "end_of_game_result",
    ):
        if name in metadata:
            kwargs[name] = metadata[name]
    return RawMatch(**kwargs)


def _legacy_unit_cost(
    *,
    unit_name: str,
    source_cost: Any,
    rarity: Any,
    patch: str | None,
    set_number: int | None,
    resolver_factory: StaticResolverFactory | None,
) -> int | None:
    """Normalize a legacy unit cost using exact-patch static metadata.

    Legacy source tables may contain either a precomputed ``cost`` or Riot's
    ``rarity``. Static champion metadata wins whenever the migration command
    is given a resolver factory, because old source values can exceed the
    game's actual shop-cost range.

    Args:
        unit_name: Legacy display name or API identifier.
        source_cost: Existing legacy cost, if present.
        rarity: Legacy zero-based Riot rarity, if present.
        patch: Match patch used to select static metadata.
        set_number: Match TFT set used to select static metadata.
        resolver_factory: Exact-patch resolver provider, or ``None`` for
            deterministic offline/test migration behavior.

    Returns:
        The resolved one-based shop cost, or ``None`` when no cost is known.
    """
    fallback = source_cost
    if fallback is None and rarity is not None:
        fallback = int(rarity) + 1
    if resolver_factory is None or not patch:
        return None if fallback is None else int(fallback)

    resolver = resolver_factory(patch, set_number)
    static_cost = resolver.unit_cost(unit_name)
    if static_cost is None:
        return None if fallback is None else int(fallback)
    if fallback is not None and int(fallback) != int(static_cost):
        logger.warning(
            "Legacy unit cost mismatch for %s in set %s: source_cost=%s "
            "rarity=%s normalized_cost=%s, Community Dragon cost=%s; using "
            "Community Dragon cost",
            unit_name,
            set_number,
            source_cost,
            rarity,
            fallback,
            static_cost,
        )
    return int(static_cost)


def _backfill_batch(
    session: Session,
    all_matches: Table,
    player_board: Table | None,
    player_units: Table | None,
    match_ids: Sequence[str],
    resolver_factory: StaticResolverFactory | None = None,
) -> dict[str, int]:
    all_rows = list(
        session.execute(
            select(all_matches).where(all_matches.c.match_id.in_(match_ids))
        ).mappings()
    )
    boards_by_key: dict[tuple[str, str], Any] = {}
    if player_board is not None:
        boards_by_key = {
            (str(row["match_id"]), str(row["puuid"])): row
            for row in session.execute(
                select(player_board).where(player_board.c.match_id.in_(match_ids))
            ).mappings()
        }
    units_by_key: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
    if player_units is not None:
        for row in session.execute(
            select(player_units).where(player_units.c.match_id.in_(match_ids))
        ).mappings():
            units_by_key[(str(row["match_id"]), str(row["puuid"]))].append(row)

    rows_by_match: defaultdict[str, list[Any]] = defaultdict(list)
    for row in all_rows:
        rows_by_match[str(row["match_id"])].append(row)
    existing = set(
        session.scalars(select(RawMatch.match_id).where(RawMatch.match_id.in_(match_ids)))
    )
    counts: Counter[str] = Counter()
    for match_id in match_ids:
        if match_id in existing or not rows_by_match.get(match_id):
            counts["skipped_existing_matches"] += 1
            continue
        metadata = rows_by_match[match_id][0]
        ingested_at = min(
            int(_mapping_value(row, "ingested_at", 0) or 0)
            for row in rows_by_match[match_id]
        )
        raw = _raw_match_from_source(match_id, metadata)
        raw.ingested_at = ingested_at
        for participant in rows_by_match[match_id]:
            puuid = str(participant["puuid"])
            key = (match_id, puuid)
            legacy_board = boards_by_key.get(key)
            unit_rows = sorted(
                units_by_key.get(key, []),
                key=lambda row: int(_mapping_value(row, "unit_idx", 0) or 0),
            )
            placement = (
                _mapping_value(legacy_board, "placement")
                if legacy_board is not None
                else None
            )
            if placement is None and unit_rows:
                placement = _mapping_value(unit_rows[0], "placement")
            board = PlayerBoard(puuid=puuid, placement=placement)
            raw.boards.append(board)
            counts["player_boards"] += 1

            for unit_row in unit_rows:
                name_column = "unit_name" if "unit_name" in unit_row else "name"
                rarity = _mapping_value(unit_row, "rarity")
                cost = _legacy_unit_cost(
                    unit_name=str(unit_row[name_column]),
                    source_cost=_mapping_value(unit_row, "cost"),
                    rarity=rarity,
                    patch=raw.patch,
                    set_number=raw.tft_set_number,
                    resolver_factory=resolver_factory,
                )
                unit = BoardUnit(
                    unit_idx=int(_mapping_value(unit_row, "unit_idx", 0) or 0),
                    unit_name=str(unit_row[name_column]),
                    star_level=int(_mapping_value(unit_row, "star_level", 0) or 0),
                    cost=cost,
                )
                board.units.append(unit)
                counts["board_units"] += 1
                for item_slot, column_name in enumerate(("item1", "item2", "item3")):
                    item_name = _mapping_value(unit_row, column_name)
                    if item_name is None or str(item_name) == "":
                        continue
                    unit.items.append(
                        UnitItem(item_slot=item_slot, item_name=str(item_name))
                    )
                    counts["unit_items"] += 1

            packed_traits = (
                _mapping_value(legacy_board, "traits", "")
                if legacy_board is not None
                else ""
            )
            parsed, malformed = parse_legacy_traits(packed_traits)
            counts["malformed_trait_segments_skipped"] += len(malformed)
            # A target board has one row per trait name.  If a malformed source
            # contains the same name twice, take the highest reached tier.
            tier_by_name: dict[str, int] = {}
            for trait_name, tier in parsed:
                tier_by_name[trait_name] = max(tier_by_name.get(trait_name, 0), tier)
            for trait_name, tier in tier_by_name.items():
                board.trait_rows.append(
                    BoardTrait(
                        trait_name=trait_name,
                        num_units=None,
                        style=1,
                        tier_current=tier,
                        tier_total=None,
                    )
                )
                counts["board_traits"] += 1
        session.add(raw)
        counts["raw_matches"] += 1
    session.commit()
    return dict(counts)


def _backfill_normalized_batch(
    session: Session,
    sources: MigrationSources,
    match_ids: Sequence[str],
    resolver_factory: StaticResolverFactory | None = None,
) -> dict[str, int]:
    metadata_by_match = {
        str(row["match_id"]): row
        for row in session.execute(
            select(sources.match_metadata).where(
                sources.match_metadata.c.match_id.in_(match_ids)
            )
        ).mappings()
    }
    participants_by_match: defaultdict[str, list[Any]] = defaultdict(list)
    for row in session.execute(
        select(sources.participants).where(
            sources.participants.c.match_id.in_(match_ids)
        )
    ).mappings():
        participants_by_match[str(row["match_id"])].append(row)

    units_by_board: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
    if sources.units is not None:
        for row in session.execute(
            select(sources.units).where(sources.units.c.match_id.in_(match_ids))
        ).mappings():
            units_by_board[(str(row["match_id"]), str(row["puuid"]))].append(row)

    items_by_source_unit: defaultdict[
        tuple[str, str, str, int], list[Any]
    ] = defaultdict(list)
    item_keys_by_board: defaultdict[
        tuple[str, str], list[tuple[str, str, str, int]]
    ] = defaultdict(list)
    if sources.items is not None:
        for row in session.execute(
            select(sources.items).where(sources.items.c.match_id.in_(match_ids))
        ).mappings():
            key = (
                str(row["match_id"]),
                str(row["puuid"]),
                str(row["character_id"]),
                int(row["unit_index"]),
            )
            if key not in items_by_source_unit:
                item_keys_by_board[(key[0], key[1])].append(key)
            items_by_source_unit[key].append(row)

    traits_by_board: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
    if sources.traits is not None:
        for row in session.execute(
            select(sources.traits).where(sources.traits.c.match_id.in_(match_ids))
        ).mappings():
            traits_by_board[(str(row["match_id"]), str(row["puuid"]))].append(row)

    existing = set(
        session.scalars(select(RawMatch.match_id).where(RawMatch.match_id.in_(match_ids)))
    )
    counts: Counter[str] = Counter()
    board_fields = (
        "riot_id_game_name",
        "riot_id_tagline",
        "placement",
        "level",
        "last_round",
        "players_eliminated",
        "total_damage_to_players",
        "gold_left",
        "time_eliminated",
        "partner_group_id",
        "companion_content_id",
        "companion_item_id",
        "companion_skin_id",
        "companion_species",
    )
    for match_id in match_ids:
        metadata = metadata_by_match.get(match_id)
        if match_id in existing or metadata is None:
            counts["skipped_existing_matches"] += 1
            continue
        raw = _raw_match_from_source(match_id, metadata)
        for participant in participants_by_match.get(match_id, []):
            puuid = str(participant["puuid"])
            board_kwargs = {
                name: participant[name]
                for name in board_fields
                if name in participant
            }
            placement = board_kwargs.get("placement")
            board_kwargs["win"] = (
                bool(participant["win"])
                if "win" in participant and participant["win"] is not None
                else placement == 1
                if placement is not None
                else None
            )
            board = PlayerBoard(puuid=puuid, **board_kwargs)
            raw.boards.append(board)
            counts["player_boards"] += 1

            unit_rows = sorted(
                units_by_board.get((match_id, puuid), []),
                key=lambda row: (
                    int(row["unit_index"]),
                    str(row["character_id"]),
                    int(_mapping_value(row, "tier", 0) or 0),
                    int(_mapping_value(row, "rarity", 0) or 0),
                ),
            )
            target_units_by_exact_source: defaultdict[
                tuple[str, int], list[BoardUnit]
            ] = defaultdict(list)
            target_units_by_character: defaultdict[str, list[BoardUnit]] = defaultdict(
                list
            )
            for unit_idx, unit_row in enumerate(unit_rows):
                rarity = _mapping_value(unit_row, "rarity")
                unit_name = str(unit_row["character_id"])
                unit = BoardUnit(
                    unit_idx=unit_idx,
                    unit_name=unit_name,
                    star_level=int(unit_row["tier"]),
                    cost=_legacy_unit_cost(
                        unit_name=unit_name,
                        source_cost=_mapping_value(unit_row, "cost"),
                        rarity=rarity,
                        patch=raw.patch,
                        set_number=raw.tft_set_number,
                        resolver_factory=resolver_factory,
                    ),
                )
                board.units.append(unit)
                counts["board_units"] += 1
                character_id = str(unit_row["character_id"])
                source_unit_idx = int(unit_row["unit_index"])
                target_units_by_exact_source[(character_id, source_unit_idx)].append(
                    unit
                )
                target_units_by_character[character_id].append(unit)

            for item_key in sorted(
                item_keys_by_board.get((match_id, puuid), []),
                key=lambda key: (key[2], key[3]),
            ):
                character_id = item_key[2]
                source_unit_idx = item_key[3]
                exact_candidates = target_units_by_exact_source.get(
                    (character_id, source_unit_idx), []
                )
                character_candidates = target_units_by_character.get(
                    character_id, []
                )
                candidates = list(exact_candidates)
                candidates.extend(
                    unit for unit in character_candidates if unit not in candidates
                )
                for item_row in sorted(
                    items_by_source_unit[item_key],
                    key=lambda row: (
                        int(row["item_index"]),
                        str(row["item_name"]),
                    ),
                ):
                    target_unit = next(
                        (unit for unit in candidates if len(unit.items) < 3),
                        None,
                    )
                    if target_unit is None:
                        counts["excess_item_rows_skipped"] += 1
                        continue
                    target_unit.items.append(
                        UnitItem(
                            item_slot=len(target_unit.items),
                            item_name=str(item_row["item_name"]),
                        )
                    )
                    counts["unit_items"] += 1

            for trait_row in traits_by_board.get((match_id, puuid), []):
                board.trait_rows.append(
                    BoardTrait(
                        trait_name=str(trait_row["trait_name"]),
                        num_units=_mapping_value(trait_row, "num_units"),
                        style=_mapping_value(trait_row, "style"),
                        tier_current=_mapping_value(trait_row, "tier_current"),
                        tier_total=_mapping_value(trait_row, "tier_total"),
                    )
                )
                counts["board_traits"] += 1
        session.add(raw)
        counts["raw_matches"] += 1
    session.commit()
    return dict(counts)


def backfill_normalized_tables(
    session: Session,
    *,
    batch_size: int = 500,
    resolver_factory: StaticResolverFactory | None = None,
) -> dict[str, int]:
    sources = _migration_sources(session)
    totals: Counter[str] = Counter()
    cursor: str | None = None
    batch_number = 0
    started = time.perf_counter()
    while True:
        match_ids = _source_match_id_page(
            session,
            sources.match_metadata,
            cursor=cursor,
            batch_size=batch_size,
        )
        if not match_ids:
            break
        batch_number += 1
        batch_started = time.perf_counter()
        batch_counts = (
            _backfill_batch(
                session,
                sources.match_metadata,
                sources.packed_boards,
                sources.units,
                match_ids,
                resolver_factory,
            )
            if sources.kind == "packed_v1"
            else _backfill_normalized_batch(
                session,
                sources,
                match_ids,
                resolver_factory,
            )
        )
        totals.update(batch_counts)
        cursor = match_ids[-1]
        logger.info(
            "raw backfill batch complete batch=%d source_matches=%d "
            "migrated_matches=%d skipped_existing_matches=%d "
            "cumulative_source_matches=%d cumulative_migrated_matches=%d "
            "cursor=%s batch_seconds=%.3f elapsed_seconds=%.3f",
            batch_number,
            len(match_ids),
            batch_counts.get("raw_matches", 0),
            batch_counts.get("skipped_existing_matches", 0),
            totals.get("raw_matches", 0) + totals.get("skipped_existing_matches", 0),
            totals.get("raw_matches", 0),
            cursor,
            time.perf_counter() - batch_started,
            time.perf_counter() - started,
        )
    return dict(totals)


def _scope_group_page(
    session: Session,
    *,
    cursor: tuple[str, int, int] | None,
    batch_size: int,
) -> list[tuple[str, int, int]]:
    set_number = func.coalesce(RawMatch.tft_set_number, 0)
    statement = (
        select(RawMatch.patch, RawMatch.queue_id, set_number.label("set_number"))
        .where(RawMatch.patch.is_not(None))
        .distinct()
    )
    if cursor is not None:
        cursor_patch, cursor_queue_id, cursor_set_number = cursor
        statement = statement.where(
            or_(
                RawMatch.patch > cursor_patch,
                and_(
                    RawMatch.patch == cursor_patch,
                    RawMatch.queue_id > cursor_queue_id,
                ),
                and_(
                    RawMatch.patch == cursor_patch,
                    RawMatch.queue_id == cursor_queue_id,
                    set_number > cursor_set_number,
                ),
            )
        )
    return [
        (str(patch), int(queue_id), int(set_number))
        for patch, queue_id, set_number in session.execute(
            statement.order_by(RawMatch.patch, RawMatch.queue_id, set_number).limit(
                max(int(batch_size), 1)
            )
        )
    ]


def build_all_analysis_scopes(
    session: Session,
    *,
    batch_size: int = 500,
) -> dict[str, Any]:
    per_scope: list[dict[str, Any]] = []
    scope_cursor: tuple[str, int, int] | None = None
    while True:
        scope_groups = _scope_group_page(
            session,
            cursor=scope_cursor,
            batch_size=batch_size,
        )
        if not scope_groups:
            break
        for patch, queue_id, set_number in scope_groups:
            scope = session.scalar(
                select(AnalysisScope).where(
                    AnalysisScope.patch == patch,
                    AnalysisScope.queue_id == queue_id,
                    AnalysisScope.tft_set_number == set_number,
                )
            )
            if scope is None:
                scope = AnalysisScope(
                    patch=patch,
                    queue_id=queue_id,
                    tft_set_number=set_number,
                    status="pending",
                )
                session.add(scope)
                session.commit()
            processed = 0
            boards = 0
            batch_number = 0
            scope_started = time.perf_counter()
            while True:
                batch = list(
                    session.scalars(
                        select(RawMatch.match_id)
                        .outerjoin(
                            AnalysisProcessedMatch,
                            and_(
                                AnalysisProcessedMatch.scope_id == scope.scope_id,
                                AnalysisProcessedMatch.match_id == RawMatch.match_id,
                            ),
                        )
                        .where(
                            RawMatch.patch == patch,
                            RawMatch.queue_id == queue_id,
                            func.coalesce(RawMatch.tft_set_number, 0) == set_number,
                            AnalysisProcessedMatch.match_id.is_(None),
                        )
                        .order_by(RawMatch.game_datetime, RawMatch.match_id)
                        .limit(max(int(batch_size), 1))
                    )
                )
                session.rollback()
                if not batch:
                    break
                batch_number += 1
                batch_started = time.perf_counter()
                result = process_match_batch(
                    session,
                    batch,
                    scope=session.get(AnalysisScope, scope.scope_id),
                    finalize=False,
                )
                processed += result["processed_matches"]
                boards += result["boards"]
                logger.info(
                    "analytics batch complete scope_id=%d patch=%s queue_id=%d "
                    "set_number=%d batch=%d requested_matches=%d "
                    "processed_matches=%d boards=%d cumulative_processed_matches=%d "
                    "cumulative_boards=%d batch_seconds=%.3f elapsed_seconds=%.3f",
                    scope.scope_id,
                    patch,
                    queue_id,
                    set_number,
                    batch_number,
                    len(batch),
                    result["processed_matches"],
                    result["boards"],
                    processed,
                    boards,
                    time.perf_counter() - batch_started,
                    time.perf_counter() - scope_started,
                )
            finalize_query_tables(
                session,
                scope=session.get(AnalysisScope, scope.scope_id),
            )
            current = session.get(AnalysisScope, scope.scope_id)
            aggregate_counts = {
                model.__tablename__: int(
                    session.scalar(
                        select(func.count()).select_from(model).where(
                            model.scope_id == scope.scope_id
                        )
                    )
                    or 0
                )
                for model in ANALYSIS_MODELS
                if model not in (AnalysisScope, AnalysisProcessedMatch)
            }
            per_scope.append(
                {
                    "scope_id": scope.scope_id,
                    "patch": patch,
                    "queue_id": queue_id,
                    "tft_set_number": set_number,
                    "processed_matches": processed,
                    "processed_boards": boards,
                    "universe_boards": int(current.universe_boards),
                    "aggregate_counts": aggregate_counts,
                }
            )
            session.rollback()
        scope_cursor = scope_groups[-1]

    configured = resolve_analysis_scope(session, activate=True)
    configured_scope_id = configured.scope_id if configured is not None else None
    if configured is not None:
        _replace_match_projection(session, configured)
    session.commit()
    return {"active_scope_id": configured_scope_id, "scopes": per_scope}


def validate_v2(session: Session) -> dict[str, Any]:
    """Compatibility wrapper for the database-layer relational validator."""
    return validate_relational_v2(session)


def _target_counts(session: Session) -> dict[str, int]:
    models = (*RAW_GRAPH_MODELS, *ANALYSIS_MODELS)
    return {model.__tablename__: _count(session, model) for model in models}


def _legacy_aggregate_counts(session: Session) -> dict[str, int]:
    inspector = inspect(session.connection())
    counts: dict[str, int] = {}
    for name in AGGREGATE_NAMES:
        legacy_name = f"{name}_legacy"
        if inspector.has_table(legacy_name):
            table = Table(legacy_name, MetaData(), autoload_with=session.connection())
            counts[legacy_name] = _count(session, table)
    return counts


def _retain_legacy_raw_tables(session: Session) -> list[str]:
    renamed: list[str] = []
    sources = _migration_sources(session)
    for table in sources.raw_tables:
        name = table.name
        if name.endswith("_legacy"):
            continue
        target = f"{name}_legacy"
        if _rename_table(session, name, target):
            renamed.append(target)
    session.commit()
    return renamed


def migrate_relational_v2(
    session: Session,
    *,
    batch_size: int = 500,
    build_analytics: bool = True,
    rename_legacy: bool = True,
    resolver_factory: StaticResolverFactory | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    preflight = migration_preflight(session)
    _assert_preflight_safe(preflight)
    renamed_analysis = _prepare_analysis_table_cutover(session)
    renamed_runtime = _prepare_runtime_table_cutover(session)
    _create_v2_schema(session)
    backfill = backfill_normalized_tables(
        session,
        batch_size=batch_size,
        resolver_factory=resolver_factory,
    )
    analysis = (
        build_all_analysis_scopes(session, batch_size=batch_size)
        if build_analytics
        else {"active_scope_id": None, "scopes": []}
    )
    validation = validate_v2(session)
    target_counts = _target_counts(session)
    comparison = {
        "legacy_aggregate_counts": _legacy_aggregate_counts(session),
        "v2_aggregate_counts": {
            name: target_counts.get(name, 0) for name in AGGREGATE_NAMES
        },
        "item_metric_note": (
            "Item placement/top-four/win values may differ where duplicate item "
            "instances previously weighted one board more than once."
        ),
    }
    renamed_raw = _retain_legacy_raw_tables(session) if rename_legacy else []
    result = {
        "preflight": preflight,
        "backfill": backfill,
        "target_counts": target_counts,
        "analysis": analysis,
        "comparison": comparison,
        "validation": validation,
        "renamed_legacy_tables": renamed_analysis + renamed_runtime + renamed_raw,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }
    logger.info("relational v2 migration complete: %s", json.dumps(result, sort_keys=True))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dsn", help="PostgreSQL DSN override")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--skip-analytics", action="store_true")
    parser.add_argument("--keep-legacy-names", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> None:
    load_config()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    target = resolve_database_target(args.dsn)
    session = sessionmaker(bind=engine_for(target), expire_on_commit=False)()
    try:
        if args.preflight_only:
            preflight = migration_preflight(session)
            result = {"preflight": preflight, "mutated": False}
        else:
            result = migrate_relational_v2(
                session,
                batch_size=args.batch_size,
                build_analytics=not args.skip_analytics,
                rename_legacy=not args.keep_legacy_names,
                resolver_factory=get_patch_resolver,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()
