"""Transactional full, incremental, and catch-up analytics builders.

Every aggregate is additive.  A per-scope processed-match ledger makes replay
idempotent, while a PostgreSQL advisory transaction lock serializes processors
for the same scope.  Full rebuilds use the same contribution code as runtime
incremental refreshes, making their results directly comparable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
import re
import threading
import time
from typing import Any, Iterable, Iterator, Sequence
from uuid import UUID, uuid5

from sqlalchemy import (
    Float,
    and_,
    cast,
    delete,
    func,
    inspect,
    insert,
    literal,
    or_,
    select,
    text,
    update,
)
from sqlalchemy.orm import Session

from common.sql import quote_identifier
from core.config import load_config

from .models import (
    ALL_STARS,
    ALL_TRAIT_TIERS,
    AllMatch,
    ANALYSIS_FACT_SCHEMA_VERSION,
    AnalysisBoard,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardTraitList,
    AnalysisBoardUnit,
    AnalysisBoardUnitList,
    AnalysisFactBuild,
    AnalysisProcessedMatch,
    AnalysisScope,
    Base,
    BoardTrait,
    BoardUnit,
    ITEM_OVERALL_UNIT_NAME,
    ItemMetadata,
    ItemStatQueryTable,
    Match,
    PlayerBoard,
    RawMatch,
    RUNTIME_MODELS,
    SET_17_TRAIT_COLUMNS,
    SET_17_UNIT_COLUMNS,
    TraitStatQueryTable,
    UnitItem,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
    utc_now,
)
from .session import migrate_unit_cost_columns
from .utils import discard_ambiguous_item_stats, extract_patch


_PATCH_VERSION_RE = re.compile(r"\d+")
_QUEUE_NAME_TO_ID = {
    "RANKED_TFT": 1100,
    "RANKED_TFT_TURBO": 1130,
    "RANKED_TFT_DOUBLE_UP": 1160,
}
_FIELD_RENAMES: dict[str, dict[str, str]] = {
    "player_units": {"name": "unit_name"},
    "player_items": {"name": "item_name", "holder": "unit_name"},
    "unit_stats": {"name": "unit_name"},
    "item_stats": {"name": "item_name", "holder": "unit_name"},
}
_AGGREGATE_MODELS = (
    UnitStatQueryTable,
    ItemStatQueryTable,
    TraitStatQueryTable,
    UnitLoadoutStatQueryTable,
)
_FACT_MODELS = (
    AnalysisBoardItem,
    AnalysisBoardTrait,
    AnalysisBoardUnit,
    AnalysisBoardTraitList,
    AnalysisBoardUnitList,
    AnalysisBoard,
)

# Application-owned, fixed namespaces. Changing either value would break the
# deterministic identity contract for rebuilt analytical facts.
ANALYSIS_LOBBY_NAMESPACE = UUID("6d7f1c65-4f2c-5d65-98c4-1a7b840e6262")
ANALYSIS_BOARD_NAMESPACE = UUID("38f53e96-f04b-56b5-8327-d45f14c9ae45")
_PROCESS_LOCKS: defaultdict[int, threading.RLock] = defaultdict(threading.RLock)
_PROCESS_LOCKS_GUARD = threading.Lock()

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisScopeIdentity:
    """The configured raw-data scope, resolved without changing the database."""

    patch: str
    queue_id: int
    tft_set_number: int


def _patch_version_key(patch: str) -> tuple[int, ...]:
    return tuple(int(part) for part in _PATCH_VERSION_RE.findall(patch)) or (0,)


def configured_queue_id() -> int:
    """Return the numeric queue id configured for analysis scopes."""
    raw = load_config().ingest.queue.strip() or "RANKED_TFT"
    if raw.isdigit():
        return int(raw)
    queue_id = _QUEUE_NAME_TO_ID.get(raw.upper())
    if queue_id is None:
        raise ValueError(
            f"Unsupported ingest queue {raw!r}; use a numeric queue_id or one of "
            f"{sorted(_QUEUE_NAME_TO_ID)}."
        )
    return queue_id


def _represented_sets_statement(patch: str, queue_id: int) -> Any:
    """Count represented sets while reusing one grouped SQL expression."""
    set_number = func.coalesce(RawMatch.tft_set_number, 0)
    return (
        select(
            set_number.label("set_number"),
            func.count(RawMatch.match_id).label("matches"),
        )
        .where(
            RawMatch.patch == patch,
            RawMatch.queue_id == queue_id,
        )
        .group_by(set_number)
    )


def resolve_configured_scope(
    session: Session,
    *,
    patch: str | None = None,
) -> AnalysisScopeIdentity | None:
    """Resolve configured patch/queue/set identity without mutating state.

    An explicit ``patch`` takes precedence over the configured ``[chat]`` patch.
    The queue always comes from ``[ingest].queue``. When no set is configured,
    the most represented set wins, with the higher set number breaking ties.
    """
    config = load_config()
    queue_id = configured_queue_id()
    requested_patch = patch if patch is not None else config.chat.patch
    selected_patch = current_patch(
        session,
        queue_id=queue_id,
        requested_patch=requested_patch,
    )
    if requested_patch is not None and selected_patch is None:
        raise ValueError(
            f"Configured TFT patch {requested_patch!r} is not present for queue {queue_id}."
        )
    if selected_patch is None:
        return None

    configured_set = config.chat.set_number
    represented_sets = _represented_sets_statement(selected_patch, queue_id)
    rows = session.execute(represented_sets).all()
    if configured_set is not None:
        selected_set = int(configured_set)
        if not any(int(row.set_number) == selected_set for row in rows):
            raise ValueError(
                f"Configured TFT set {selected_set} is not present for patch "
                f"{selected_patch!r} and queue {queue_id}."
            )
    else:
        if not rows:
            return None
        selected_set = int(
            max(rows, key=lambda row: (int(row.matches), int(row.set_number))).set_number
        )
    return AnalysisScopeIdentity(
        patch=str(selected_patch),
        queue_id=queue_id,
        tft_set_number=selected_set,
    )


def _normalize_field_names(session: Session) -> int:
    """Finish older name/cost migrations before the v2 maintenance cutover."""
    changed = migrate_unit_cost_columns(session, schema=None)
    connection = session.connection()
    inspector = inspect(connection)
    for table_name, renames in _FIELD_RENAMES.items():
        if not inspector.has_table(table_name):
            continue
        existing = {column["name"] for column in inspector.get_columns(table_name)}
        for old_name, new_name in renames.items():
            if new_name in existing or old_name not in existing:
                continue
            session.execute(
                text(
                    f"ALTER TABLE {quote_identifier(table_name)} RENAME COLUMN "
                    f"{quote_identifier(old_name)} TO {quote_identifier(new_name)}"
                )
            )
            existing.remove(old_name)
            existing.add(new_name)
            changed += 1
    return changed


def _ensure_query_table_schema(session: Session) -> None:
    """Create missing v2 tables; destructive shape changes belong to migration."""
    Base.metadata.create_all(
        bind=session.connection(),
        tables=[model.__table__ for model in RUNTIME_MODELS],
    )


def _legacy_rows_present(session: Session) -> bool:
    if not inspect(session.connection()).has_table(AllMatch.__tablename__):
        return False
    return bool(session.query(AllMatch.match_id).first())


def _ensure_normalized_legacy_seed(session: Session) -> int:
    """Bridge legacy-only fixtures/databases until the maintenance migration runs.

    Production rollout uses ``scripts/migrate_relational_v2.py``.  This small,
    non-destructive bridge is useful for a freshly upgraded developer database:
    it copies only match metadata and missing board shells, never overwriting v2
    rows or pretending ambiguous legacy ``player_items`` identify a holder.
    """
    if not _legacy_rows_present(session):
        return 0
    copied = 0
    legacy_rows = session.query(AllMatch).order_by(AllMatch.match_id, AllMatch.puuid).all()
    first_by_match: dict[str, AllMatch] = {}
    participants: set[tuple[str, str]] = set()
    for row in legacy_rows:
        first_by_match.setdefault(row.match_id, row)
        participants.add((row.match_id, row.puuid))
    existing_matches = set(
        session.scalars(
            select(RawMatch.match_id).where(RawMatch.match_id.in_(first_by_match))
        )
    )
    for match_id, row in first_by_match.items():
        if match_id in existing_matches:
            continue
        session.add(
            RawMatch(
                match_id=match_id,
                region=row.region,
                platform=row.platform,
                game_datetime=row.game_datetime,
                game_length=row.game_length,
                game_version=row.game_version,
                patch=row.patch or extract_patch(row.game_version),
                queue_id=row.queue_id,
                tft_set_number=row.tft_set_number,
                tft_set_core_name=row.tft_set_core_name,
                ingested_at=row.ingested_at,
            )
        )
        copied += 1
    session.flush()

    existing_boards = set(
        session.execute(select(PlayerBoard.match_id, PlayerBoard.puuid)).all()
    )
    for match_id, puuid in sorted(participants - existing_boards):
        units = session.scalars(
            select(BoardUnit).where(
                BoardUnit.match_id == match_id,
                BoardUnit.puuid == puuid,
            )
        ).all()
        placement = next(
            (
                int(value)
                for unit in units
                if (value := getattr(unit, "_legacy_placement", None)) is not None
            ),
            None,
        )
        session.add(PlayerBoard(match_id=match_id, puuid=puuid, placement=placement))
        copied += 1
    session.flush()
    return copied


def current_patch(
    session: Session,
    *,
    queue_id: int | None = None,
    requested_patch: str | None = None,
) -> str | None:
    """Return a configured patch when represented, otherwise numeric latest."""
    query = select(RawMatch.patch).where(RawMatch.patch.is_not(None))
    if queue_id is not None:
        query = query.where(RawMatch.queue_id == queue_id)
    if requested_patch is not None:
        normalized = extract_patch(requested_patch) or requested_patch
        return (
            str(normalized)
            if session.scalar(
                select(RawMatch.match_id).where(
                    RawMatch.patch == normalized,
                    *(() if queue_id is None else (RawMatch.queue_id == queue_id,)),
                ).limit(1)
            )
            is not None
            else None
        )
    patches = [str(value) for value in session.scalars(query.distinct()) if value]
    return max(patches, key=_patch_version_key) if patches else None


def _scope_match_clause(scope: AnalysisScope) -> Any:
    return and_(
        RawMatch.patch == scope.patch,
        RawMatch.queue_id == scope.queue_id,
        func.coalesce(RawMatch.tft_set_number, 0) == scope.tft_set_number,
    )


def resolve_analysis_scope(
    session: Session,
    *,
    patch: str | None = None,
    activate: bool = True,
) -> AnalysisScope | None:
    """Resolve or create the configured patch/queue/set analysis scope."""
    _ensure_query_table_schema(session)
    _ensure_normalized_legacy_seed(session)
    identity = resolve_configured_scope(session, patch=patch)
    if identity is None:
        return None

    scope = session.scalar(
        select(AnalysisScope).where(
            AnalysisScope.patch == identity.patch,
            AnalysisScope.queue_id == identity.queue_id,
            AnalysisScope.tft_set_number == identity.tft_set_number,
        )
    )
    if scope is None:
        scope = AnalysisScope(
            patch=identity.patch,
            queue_id=identity.queue_id,
            tft_set_number=identity.tft_set_number,
            status="pending",
        )
        session.add(scope)
        session.flush()
    if activate and not scope.is_active:
        session.execute(
            update(AnalysisScope)
            .where(AnalysisScope.is_active.is_(True), AnalysisScope.scope_id != scope.scope_id)
            .values(is_active=False)
        )
        scope.is_active = True
        session.flush()
    return scope


def active_analysis_scope(session: Session) -> AnalysisScope | None:
    return session.scalar(select(AnalysisScope).where(AnalysisScope.is_active.is_(True)))


def _process_lock(scope_id: int) -> threading.RLock:
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS[scope_id]


@contextmanager
def _scope_transaction_lock(session: Session, scope_id: int) -> Iterator[None]:
    """Serialize one scope in-process and with PostgreSQL transaction locking."""
    lock = _process_lock(scope_id)
    with lock:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(:scope_id)"),
                {"scope_id": int(scope_id)},
            )
        yield


def _canonical_loadout(items: Iterable[str]) -> tuple[str, list[str]]:
    ordered = sorted(items)
    return json.dumps(ordered, ensure_ascii=False, separators=(",", ":")), ordered


def anonymous_lobby_key(scope_id: int, match_id: str) -> str:
    """Return the stable opaque lobby key used only inside analytical facts."""
    return str(uuid5(ANALYSIS_LOBBY_NAMESPACE, f"{scope_id}:{match_id}"))


def anonymous_board_key(scope_id: int, match_id: str, puuid: str) -> str:
    """Return the stable opaque board key used only inside analytical facts."""
    return str(uuid5(ANALYSIS_BOARD_NAMESPACE, f"{scope_id}:{match_id}:{puuid}"))


def _new_summary(**dimensions: Any) -> dict[str, Any]:
    return {
        **dimensions,
        "placement_sum": 0,
        "outcome_count": 0,
        "top4_count": 0,
        "win_count": 0,
    }


def _add_outcome(
    summary: dict[str, Any],
    placement: int | None,
    count_field: str,
) -> None:
    summary[count_field] = int(summary.get(count_field, 0)) + 1
    if placement is None:
        return
    summary["outcome_count"] += 1
    summary["placement_sum"] += placement
    summary["top4_count"] += int(placement <= 4)
    summary["win_count"] += int(placement == 1)


def _dialect_insert(session: Session, model: type[Any]) -> Any:
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert

        return dialect_insert(model)
    if dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as dialect_insert

        return dialect_insert(model)
    return None


def _upsert_additive(
    session: Session,
    model: type[Any],
    rows: list[dict[str, Any]],
    additive_fields: Sequence[str],
    *,
    max_fields: Sequence[str] = (),
) -> None:
    if not rows:
        return
    statement = _dialect_insert(session, model)
    pk_names = [column.name for column in model.__table__.primary_key.columns]
    if statement is not None:
        excluded = statement.excluded
        updates = {
            name: getattr(model, name) + getattr(excluded, name)
            for name in additive_fields
        }
        for name in max_fields:
            greatest = (
                func.greatest(getattr(model, name), getattr(excluded, name))
                if session.get_bind().dialect.name == "postgresql"
                else func.max(getattr(model, name), getattr(excluded, name))
            )
            updates[name] = func.coalesce(
                greatest,
                getattr(model, name),
                getattr(excluded, name),
            )
        statement = statement.on_conflict_do_update(
            index_elements=[getattr(model, name) for name in pk_names],
            set_=updates,
        )
        session.execute(statement, rows)
        return

    # Non-production fallback for dialects without ON CONFLICT support.
    for mapping in rows:
        identity = tuple(mapping[name] for name in pk_names)
        existing = session.get(model, identity if len(identity) > 1 else identity[0])
        if existing is None:
            session.add(model(**mapping))
            continue
        for name in additive_fields:
            setattr(existing, name, int(getattr(existing, name) or 0) + int(mapping[name]))
        for name in max_fields:
            values = [value for value in (getattr(existing, name), mapping[name]) if value is not None]
            setattr(existing, name, max(values) if values else None)


def validate_item_stat_metadata(
    session: Session,
    rows: Sequence[dict[str, Any]],
) -> None:
    """Reject aggregate identity or classification drift across catch-up batches.

    Args:
        session: Analytics transaction receiving additive projection rows.
        rows: Candidate item-stat mappings for the current match batch.

    Raises:
        RuntimeError: If an existing aggregate key has different canonical
            item identity or family metadata.
    """
    for row in rows:
        identity = (row["scope_id"], row["item_name"], row["unit_name"])
        existing = session.get(ItemStatQueryTable, identity)
        if existing is None:
            continue
        expected = (row["item_api_name"], row["item_type"])
        actual = (existing.item_api_name, existing.item_type)
        if actual != expected:
            raise RuntimeError(
                f"Conflicting item_stats metadata for {identity!r}: "
                f"stored={actual!r}, observed={expected!r}"
            )


def _contribution_rows(
    session: Session,
    scope: AnalysisScope,
    match_ids: Sequence[str],
    excluded_item_names: set[str],
) -> tuple[
    dict[type[Any], list[dict[str, Any]]],
    dict[type[Any], list[dict[str, Any]]],
    dict[str, int],
]:
    """Build board-deduplicated additive rows from explicit set-based reads."""
    board_rows = session.execute(
        select(
            PlayerBoard.match_id,
            PlayerBoard.puuid,
            PlayerBoard.placement,
            PlayerBoard.level,
            PlayerBoard.last_round,
            PlayerBoard.players_eliminated,
            PlayerBoard.total_damage_to_players,
            PlayerBoard.gold_left,
            PlayerBoard.time_eliminated,
            PlayerBoard.win,
            RawMatch.region,
            RawMatch.platform,
            RawMatch.game_length,
        )
        .join(RawMatch, RawMatch.match_id == PlayerBoard.match_id)
        .where(PlayerBoard.match_id.in_(match_ids))
    ).all()
    board_keys = {(row.match_id, row.puuid) for row in board_rows}
    placements = {
        (row.match_id, row.puuid): int(row.placement)
        for row in board_rows
        if row.placement is not None
    }
    unit_rows = session.execute(
        select(
            BoardUnit.match_id,
            BoardUnit.puuid,
            BoardUnit.unit_idx,
            BoardUnit.unit_name,
            BoardUnit.star_level,
            BoardUnit.cost,
        ).where(BoardUnit.match_id.in_(match_ids))
    ).all()
    item_rows = session.execute(
        select(
            UnitItem.match_id,
            UnitItem.puuid,
            UnitItem.unit_idx,
            UnitItem.item_slot,
            UnitItem.item_api_name,
            UnitItem.item_name,
        ).where(UnitItem.match_id.in_(match_ids))
    ).all()
    trait_rows = session.execute(
        select(
            BoardTrait.match_id,
            BoardTrait.puuid,
            BoardTrait.trait_name,
            BoardTrait.num_units,
            BoardTrait.style,
            BoardTrait.tier_current,
            BoardTrait.tier_total,
        ).where(BoardTrait.match_id.in_(match_ids))
    ).all()

    units_by_board: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
    unit_by_key: dict[tuple[str, str, int], Any] = {}
    for row in unit_rows:
        key = (row.match_id, row.puuid)
        if key not in board_keys:
            continue
        units_by_board[key].append(row)
        unit_by_key[(row.match_id, row.puuid, row.unit_idx)] = row
    metadata_by_api_name = {
        row.item_api_name: row
        for row in session.scalars(
            select(ItemMetadata).where(
                ItemMetadata.patch == scope.patch,
                ItemMetadata.tft_set_number == scope.tft_set_number,
            )
        )
    }
    items_by_unit: defaultdict[
        tuple[str, str, int], list[tuple[int, str, str, str]]
    ] = defaultdict(list)
    item_details_by_name: dict[str, tuple[str, str]] = {}
    for row in item_rows:
        key = (row.match_id, row.puuid, row.unit_idx)
        if key not in unit_by_key:
            continue
        metadata = metadata_by_api_name.get(str(row.item_api_name))
        if metadata is None:
            raise RuntimeError(
                "Missing item metadata for "
                f"patch={scope.patch!r}, set={scope.tft_set_number}, "
                f"api_name={row.item_api_name!r}"
            )
        if metadata.item_name != row.item_name:
            raise RuntimeError(
                f"Item display-name mismatch for {row.item_api_name!r}: "
                f"metadata={metadata.item_name!r}, raw={row.item_name!r}"
            )
        details = (str(row.item_api_name), str(metadata.item_type))
        if str(row.item_name) not in excluded_item_names:
            item_details_by_name[str(row.item_name)] = details
        items_by_unit[key].append(
            (
                int(row.item_slot),
                str(row.item_api_name),
                str(row.item_name),
                str(metadata.item_type),
            )
        )
    trait_rows_by_board: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
    active_traits_by_board: defaultdict[
        tuple[str, str], set[tuple[str, int]]
    ] = defaultdict(set)
    for row in trait_rows:
        key = (row.match_id, row.puuid)
        if key not in board_keys:
            continue
        trait_rows_by_board[key].append(row)
        if (
            int(row.style or 0) > 0
            and int(row.tier_current or 0) > 0
        ):
            active_traits_by_board[key].add(
                (row.trait_name, int(row.tier_current))
            )

    unit: dict[tuple[str, int], dict[str, Any]] = {}
    item: dict[tuple[str, str], dict[str, Any]] = {}
    trait: dict[tuple[str, int], dict[str, Any]] = {}
    loadout: dict[tuple[str, int, str], dict[str, Any]] = {}

    for board_key in board_keys:
        placement = placements.get(board_key)
        board_units = units_by_board.get(board_key, [])
        max_star_by_name: dict[str, int] = {}
        max_cost_by_name: dict[str, int | None] = {}
        actual_unit_keys: set[tuple[str, int]] = set()
        for row in board_units:
            name = str(row.unit_name)
            star = int(row.star_level)
            actual_unit_keys.add((name, star))
            max_star_by_name[name] = max(max_star_by_name.get(name, 0), star)
            current_cost = max_cost_by_name.get(name)
            if row.cost is not None:
                max_cost_by_name[name] = max(current_cost or int(row.cost), int(row.cost))
            else:
                max_cost_by_name.setdefault(name, None)
        for name, star in actual_unit_keys | {(name, ALL_STARS) for name in max_star_by_name}:
            key = (name, star)
            summary = unit.setdefault(
                key,
                _new_summary(
                    scope_id=scope.scope_id,
                    unit_name=name,
                    star_level=star,
                    tft_set_number=scope.tft_set_number,
                    cost=max_cost_by_name.get(name),
                    games=0,
                    avg_placement=None,
                    top4_rate=None,
                    win_rate=None,
                    pick_rate=None,
                    universe_games=0,
                ),
            )
            if max_cost_by_name.get(name) is not None:
                summary["cost"] = max(summary.get("cost") or 0, max_cost_by_name[name] or 0)
            _add_outcome(summary, placement, "games")

        hold_counts: Counter[tuple[str, str]] = Counter()
        item_board_keys: set[tuple[str, str]] = set()
        loadout_board_keys: set[tuple[str, int, str, tuple[str, ...]]] = set()
        for row in board_units:
            unit_key = (row.match_id, row.puuid, row.unit_idx)
            names = [
                name
                for _slot, _api_name, name, _item_type in sorted(
                    items_by_unit.get(unit_key, [])
                )
            ]
            for item_name in names:
                # Ambiguous display names remain in slot-level facts and loadouts,
                # but cannot represent one canonical identity in item rankings.
                if item_name in excluded_item_names:
                    continue
                hold_counts[(item_name, str(row.unit_name))] += 1
                hold_counts[(item_name, ITEM_OVERALL_UNIT_NAME)] += 1
                item_board_keys.add((item_name, str(row.unit_name)))
                item_board_keys.add((item_name, ITEM_OVERALL_UNIT_NAME))
            if names:
                loadout_key, ordered = _canonical_loadout(names)
                for star in {int(row.star_level), ALL_STARS}:
                    loadout_board_keys.add(
                        (str(row.unit_name), star, loadout_key, tuple(ordered))
                    )
        for key, holds in hold_counts.items():
            summary = item.setdefault(
                key,
                _new_summary(
                    scope_id=scope.scope_id,
                    item_name=key[0],
                    unit_name=key[1],
                    item_api_name=item_details_by_name[key[0]][0],
                    item_type=item_details_by_name[key[0]][1],
                    tft_set_number=scope.tft_set_number,
                    holds=0,
                    boards=0,
                    avg_placement=None,
                    top4_rate=None,
                    win_rate=None,
                    pick_rate_per_board=None,
                    universe_games=0,
                ),
            )
            summary["holds"] += holds
        for key in item_board_keys:
            _add_outcome(item[key], placement, "boards")

        for name, star, loadout_key, ordered_items in loadout_board_keys:
            key = (name, star, loadout_key)
            padded = list(ordered_items) + [None, None, None]
            summary = loadout.setdefault(
                key,
                _new_summary(
                    scope_id=scope.scope_id,
                    unit_name=name,
                    star_level=star,
                    loadout_key=loadout_key,
                    item_count=len(ordered_items),
                    item_1=padded[0],
                    item_2=padded[1],
                    item_3=padded[2],
                    boards=0,
                    avg_placement=None,
                    top4_rate=None,
                    win_rate=None,
                    unit_boards=0,
                    loadout_pick_rate=None,
                ),
            )
            _add_outcome(summary, placement, "boards")

        active_traits = active_traits_by_board.get(board_key, set())
        for trait_name, tier_value in active_traits:
            for tier in {tier_value, ALL_TRAIT_TIERS}:
                key = (trait_name, tier)
                summary = trait.setdefault(
                    key,
                    _new_summary(
                        scope_id=scope.scope_id,
                        trait_name=trait_name,
                        tier=tier,
                        tft_set_number=scope.tft_set_number,
                        games=0,
                        avg_placement=None,
                        top4_rate=None,
                        win_rate=None,
                        pick_rate=None,
                        universe_games=0,
                    ),
                )
                _add_outcome(summary, placement, "games")

    rows_by_model = {
        UnitStatQueryTable: list(unit.values()),
        ItemStatQueryTable: list(item.values()),
        TraitStatQueryTable: list(trait.values()),
        UnitLoadoutStatQueryTable: list(loadout.values()),
    }
    fact_boards: list[dict[str, Any]] = []
    fact_unit_lists: list[dict[str, Any]] = []
    fact_trait_lists: list[dict[str, Any]] = []
    fact_units: list[dict[str, Any]] = []
    fact_items: list[dict[str, Any]] = []
    fact_traits: list[dict[str, Any]] = []
    board_row_by_key = {(row.match_id, row.puuid): row for row in board_rows}
    for raw_key in sorted(board_keys):
        board_row = board_row_by_key[raw_key]
        match_id, puuid = raw_key
        board_key = anonymous_board_key(scope.scope_id, match_id, puuid)
        board_units = sorted(units_by_board.get(raw_key, []), key=lambda row: row.unit_idx)
        unit_features = {column: 0 for column in SET_17_UNIT_COLUMNS.values()}
        for unit_row in board_units:
            feature_column = SET_17_UNIT_COLUMNS.get(str(unit_row.unit_name))
            if feature_column is not None:
                unit_features[feature_column] = max(
                    unit_features[feature_column], int(unit_row.star_level)
                )
        trait_features = {column: 0 for column in SET_17_TRAIT_COLUMNS.values()}
        for trait_row in trait_rows_by_board.get(raw_key, ()):
            feature_column = SET_17_TRAIT_COLUMNS.get(str(trait_row.trait_name))
            if feature_column is not None and int(trait_row.style or 0) > 0:
                trait_features[feature_column] = max(
                    trait_features[feature_column], int(trait_row.tier_current or 0)
                )
        board_item_count = 0
        for unit_row in board_units:
            unit_key = (match_id, puuid, int(unit_row.unit_idx))
            held = sorted(items_by_unit.get(unit_key, []))
            held_names = [name for _slot, _api_name, name, _item_type in held]
            loadout_key, ordered = _canonical_loadout(held_names)
            padded = ordered + [None, None, None]
            fact_units.append(
                {
                    "scope_id": scope.scope_id,
                    "board_key": board_key,
                    "unit_idx": int(unit_row.unit_idx),
                    "unit_name": str(unit_row.unit_name),
                    "star_level": int(unit_row.star_level),
                    "cost": None if unit_row.cost is None else int(unit_row.cost),
                    "completed_item_count": len(held),
                    "loadout_key": loadout_key,
                    "item_1": padded[0],
                    "item_2": padded[1],
                    "item_3": padded[2],
                }
            )
            board_item_count += len(held)
            fact_items.extend(
                {
                    "scope_id": scope.scope_id,
                    "board_key": board_key,
                    "unit_idx": int(unit_row.unit_idx),
                    "item_slot": int(slot),
                    "item_api_name": str(api_name),
                    "item_name": str(name),
                }
                for slot, api_name, name, _item_type in held
            )
        fact_boards.append(
            {
                "scope_id": scope.scope_id,
                "board_key": board_key,
                "lobby_key": anonymous_lobby_key(scope.scope_id, match_id),
                "placement": board_row.placement,
                "level": board_row.level,
                "last_round": board_row.last_round,
                "eliminations": board_row.players_eliminated,
                "player_damage": board_row.total_damage_to_players,
                "gold_left": board_row.gold_left,
                "elimination_time": board_row.time_eliminated,
                "win": board_row.win,
                "region": board_row.region,
                "platform": board_row.platform,
                "game_length": float(board_row.game_length),
                "unit_count": len(board_units),
                "completed_item_count": board_item_count,
            }
        )
        fact_unit_lists.append(
            {"scope_id": scope.scope_id, "board_key": board_key, **unit_features}
        )
        fact_trait_lists.append(
            {"scope_id": scope.scope_id, "board_key": board_key, **trait_features}
        )
        fact_traits.extend(
            {
                "scope_id": scope.scope_id,
                "board_key": board_key,
                "trait_name": str(row.trait_name),
                "num_units": row.num_units,
                "style": row.style,
                "tier_current": row.tier_current,
                "tier_total": row.tier_total,
            }
            for row in trait_rows_by_board.get(raw_key, ())
        )
    fact_rows_by_model = {
        AnalysisBoard: fact_boards,
        AnalysisBoardUnitList: fact_unit_lists,
        AnalysisBoardTraitList: fact_trait_lists,
        AnalysisBoardUnit: fact_units,
        AnalysisBoardItem: fact_items,
        AnalysisBoardTrait: fact_traits,
    }
    board_counts = Counter(row.match_id for row in board_rows)
    return (
        rows_by_model,
        fact_rows_by_model,
        {match_id: int(board_counts.get(match_id, 0)) for match_id in match_ids},
    )


def _ratio(numerator: Any, denominator: Any) -> Any:
    return cast(numerator, Float) / func.nullif(cast(denominator, Float), 0.0)


def _insert_fact_rows(
    session: Session, rows_by_model: dict[type[Any], list[dict[str, Any]]]
) -> None:
    """Insert facts strictly; a collision without ledger evidence is corruption."""
    for model in (
        AnalysisBoard,
        AnalysisBoardUnitList,
        AnalysisBoardTraitList,
        AnalysisBoardUnit,
        AnalysisBoardItem,
        AnalysisBoardTrait,
    ):
        rows = rows_by_model.get(model, [])
        if rows:
            session.execute(insert(model), rows)


def _fact_build(session: Session, scope_id: int) -> AnalysisFactBuild:
    build = session.get(AnalysisFactBuild, scope_id)
    if build is None:
        build = AnalysisFactBuild(
            scope_id=scope_id,
            schema_version=ANALYSIS_FACT_SCHEMA_VERSION,
            status="incomplete",
        )
        session.add(build)
        session.flush()
    return build


def _fact_source_counts(session: Session, scope: AnalysisScope) -> dict[str, int]:
    match_clause = _scope_match_clause(scope)
    return {
        "processed_matches": int(
            session.scalar(
                select(func.count()).select_from(AnalysisProcessedMatch).where(
                    AnalysisProcessedMatch.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "lobbies": int(
            session.scalar(select(func.count()).select_from(RawMatch).where(match_clause))
            or 0
        ),
        "boards": int(
            session.scalar(
                select(func.count())
                .select_from(PlayerBoard)
                .join(RawMatch, RawMatch.match_id == PlayerBoard.match_id)
                .where(match_clause)
            )
            or 0
        ),
        "units": int(
            session.scalar(
                select(func.count())
                .select_from(BoardUnit)
                .join(RawMatch, RawMatch.match_id == BoardUnit.match_id)
                .where(match_clause)
            )
            or 0
        ),
        "items": int(
            session.scalar(
                select(func.count())
                .select_from(UnitItem)
                .join(RawMatch, RawMatch.match_id == UnitItem.match_id)
                .where(match_clause)
            )
            or 0
        ),
        "traits": int(
            session.scalar(
                select(func.count())
                .select_from(BoardTrait)
                .join(RawMatch, RawMatch.match_id == BoardTrait.match_id)
                .where(match_clause)
            )
            or 0
        ),
    }


def fact_validation(
    session: Session,
    scope: AnalysisScope,
    *,
    require_ready: bool = False,
) -> dict[str, Any]:
    """Validate and publish the anonymous fact layer for one analysis scope."""
    session.flush()
    source = _fact_source_counts(session, scope)
    actual = {
        "lobbies": int(
            session.scalar(
                select(func.count(func.distinct(AnalysisBoard.lobby_key))).where(
                    AnalysisBoard.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "boards": int(
            session.scalar(
                select(func.count()).select_from(AnalysisBoard).where(
                    AnalysisBoard.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "unit_lists": int(
            session.scalar(
                select(func.count()).select_from(AnalysisBoardUnitList).where(
                    AnalysisBoardUnitList.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "trait_lists": int(
            session.scalar(
                select(func.count()).select_from(AnalysisBoardTraitList).where(
                    AnalysisBoardTraitList.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "units": int(
            session.scalar(
                select(func.count()).select_from(AnalysisBoardUnit).where(
                    AnalysisBoardUnit.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "items": int(
            session.scalar(
                select(func.count()).select_from(AnalysisBoardItem).where(
                    AnalysisBoardItem.scope_id == scope.scope_id
                )
            )
            or 0
        ),
        "traits": int(
            session.scalar(
                select(func.count()).select_from(AnalysisBoardTrait).where(
                    AnalysisBoardTrait.scope_id == scope.scope_id
                )
            )
            or 0
        ),
    }
    unit_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardUnit)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardUnit.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardUnit.board_key,
                ),
            )
            .where(
                AnalysisBoardUnit.scope_id == scope.scope_id,
                AnalysisBoard.board_key.is_(None),
            )
        )
        or 0
    )
    item_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardItem)
            .outerjoin(
                AnalysisBoardUnit,
                and_(
                    AnalysisBoardUnit.scope_id == AnalysisBoardItem.scope_id,
                    AnalysisBoardUnit.board_key == AnalysisBoardItem.board_key,
                    AnalysisBoardUnit.unit_idx == AnalysisBoardItem.unit_idx,
                ),
            )
            .where(
                AnalysisBoardItem.scope_id == scope.scope_id,
                AnalysisBoardUnit.board_key.is_(None),
            )
        )
        or 0
    )
    trait_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardTrait)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardTrait.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardTrait.board_key,
                ),
            )
            .where(
                AnalysisBoardTrait.scope_id == scope.scope_id,
                AnalysisBoard.board_key.is_(None),
            )
        )
        or 0
    )
    unit_list_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardUnitList)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardUnitList.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardUnitList.board_key,
                ),
            )
            .where(
                AnalysisBoardUnitList.scope_id == scope.scope_id,
                AnalysisBoard.board_key.is_(None),
            )
        )
        or 0
    )
    trait_list_orphans = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardTraitList)
            .outerjoin(
                AnalysisBoard,
                and_(
                    AnalysisBoard.scope_id == AnalysisBoardTraitList.scope_id,
                    AnalysisBoard.board_key == AnalysisBoardTraitList.board_key,
                ),
            )
            .where(
                AnalysisBoardTraitList.scope_id == scope.scope_id,
                AnalysisBoard.board_key.is_(None),
            )
        )
        or 0
    )
    fact_metadata_missing = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardItem)
            .outerjoin(
                ItemMetadata,
                and_(
                    ItemMetadata.patch == scope.patch,
                    ItemMetadata.tft_set_number == scope.tft_set_number,
                    ItemMetadata.item_api_name == AnalysisBoardItem.item_api_name,
                ),
            )
            .where(
                AnalysisBoardItem.scope_id == scope.scope_id,
                or_(
                    AnalysisBoardItem.item_api_name == "",
                    ItemMetadata.item_api_name.is_(None),
                ),
            )
        )
        or 0
    )
    fact_metadata_mismatched = int(
        session.scalar(
            select(func.count())
            .select_from(AnalysisBoardItem)
            .join(
                ItemMetadata,
                and_(
                    ItemMetadata.patch == scope.patch,
                    ItemMetadata.tft_set_number == scope.tft_set_number,
                    ItemMetadata.item_api_name == AnalysisBoardItem.item_api_name,
                ),
            )
            .where(
                AnalysisBoardItem.scope_id == scope.scope_id,
                ItemMetadata.item_name != AnalysisBoardItem.item_name,
            )
        )
        or 0
    )
    aggregate_metadata_missing = int(
        session.scalar(
            select(func.count())
            .select_from(ItemStatQueryTable)
            .outerjoin(
                ItemMetadata,
                and_(
                    ItemMetadata.patch == scope.patch,
                    ItemMetadata.tft_set_number == scope.tft_set_number,
                    ItemMetadata.item_api_name == ItemStatQueryTable.item_api_name,
                ),
            )
            .where(
                ItemStatQueryTable.scope_id == scope.scope_id,
                or_(
                    ItemStatQueryTable.item_api_name == "",
                    ItemMetadata.item_api_name.is_(None),
                ),
            )
        )
        or 0
    )
    aggregate_metadata_mismatched = int(
        session.scalar(
            select(func.count())
            .select_from(ItemStatQueryTable)
            .join(
                ItemMetadata,
                and_(
                    ItemMetadata.patch == scope.patch,
                    ItemMetadata.tft_set_number == scope.tft_set_number,
                    ItemMetadata.item_api_name == ItemStatQueryTable.item_api_name,
                ),
            )
            .where(
                ItemStatQueryTable.scope_id == scope.scope_id,
                or_(
                    ItemMetadata.item_name != ItemStatQueryTable.item_name,
                    ItemMetadata.item_type != ItemStatQueryTable.item_type,
                ),
            )
        )
        or 0
    )
    raw_identifier_names = {
        "match_id", "puuid", "riot_id_game_name", "riot_id_tagline",
        "game_datetime", "game_creation", "ingested_at",
    }
    schema_inspector = inspect(session.connection())
    leaked_columns = sorted(
        {
            f"{model.__tablename__}.{column['name']}"
            for model in (
                AnalysisBoard,
                AnalysisBoardUnitList,
                AnalysisBoardTraitList,
                AnalysisBoardUnit,
                AnalysisBoardItem,
                AnalysisBoardTrait,
            )
            for column in schema_inspector.get_columns(model.__tablename__)
            if column["name"] in raw_identifier_names
        }
    )
    orphans = {
        "unit_lists": unit_list_orphans,
        "trait_lists": trait_list_orphans,
        "units": unit_orphans,
        "items": item_orphans,
        "traits": trait_orphans,
    }
    counts_match = (
        source["processed_matches"] == source["lobbies"]
        and all(
            actual[name] == source[name]
            for name in ("lobbies", "boards", "units", "items", "traits")
        )
        and actual["unit_lists"] == source["boards"]
        and actual["trait_lists"] == source["boards"]
    )
    metadata_coverage = {
        "fact_missing": fact_metadata_missing,
        "fact_mismatched": fact_metadata_mismatched,
        "aggregate_missing": aggregate_metadata_missing,
        "aggregate_mismatched": aggregate_metadata_mismatched,
    }
    ready = (
        counts_match
        and not any(orphans.values())
        and not any(metadata_coverage.values())
        and not leaked_columns
    )
    build = _fact_build(session, scope.scope_id)
    now = utc_now()
    build.schema_version = ANALYSIS_FACT_SCHEMA_VERSION
    build.processed_match_count = source["processed_matches"]
    build.lobby_count = actual["lobbies"]
    build.board_count = actual["boards"]
    build.unit_count = actual["units"]
    build.item_count = actual["items"]
    build.trait_count = actual["traits"]
    build.updated_at = now
    build.status = "ready" if ready else "incomplete"
    build.ready_at = now if ready else None
    build.last_error_at = None if ready else now
    build.last_error_details = None if ready else "anonymous fact validation incomplete"
    result = {
        "ready": ready,
        "schema_version": build.schema_version,
        "source": source,
        "actual": actual,
        "orphans": orphans,
        "item_metadata": metadata_coverage,
        "raw_identifier_columns": leaked_columns,
    }
    if require_ready and not ready:
        raise RuntimeError(f"anonymous fact validation failed: {result}")
    return result


def _recalculate_published_metrics(session: Session, scope: AnalysisScope) -> None:
    universe = int(
        session.scalar(
            select(func.coalesce(func.sum(AnalysisProcessedMatch.board_count), 0)).where(
                AnalysisProcessedMatch.scope_id == scope.scope_id
            )
        )
        or 0
    )
    scope.universe_boards = universe
    session.execute(
        update(UnitStatQueryTable)
        .where(UnitStatQueryTable.scope_id == scope.scope_id)
        .values(
            avg_placement=_ratio(UnitStatQueryTable.placement_sum, UnitStatQueryTable.outcome_count),
            top4_rate=_ratio(UnitStatQueryTable.top4_count, UnitStatQueryTable.outcome_count),
            win_rate=_ratio(UnitStatQueryTable.win_count, UnitStatQueryTable.outcome_count),
            pick_rate=_ratio(UnitStatQueryTable.games, literal(universe)),
            universe_games=universe,
        )
    )
    session.execute(
        update(ItemStatQueryTable)
        .where(ItemStatQueryTable.scope_id == scope.scope_id)
        .values(
            avg_placement=_ratio(ItemStatQueryTable.placement_sum, ItemStatQueryTable.outcome_count),
            top4_rate=_ratio(ItemStatQueryTable.top4_count, ItemStatQueryTable.outcome_count),
            win_rate=_ratio(ItemStatQueryTable.win_count, ItemStatQueryTable.outcome_count),
            pick_rate_per_board=_ratio(ItemStatQueryTable.boards, literal(universe)),
            universe_games=universe,
        )
    )
    session.execute(
        update(TraitStatQueryTable)
        .where(TraitStatQueryTable.scope_id == scope.scope_id)
        .values(
            avg_placement=_ratio(TraitStatQueryTable.placement_sum, TraitStatQueryTable.outcome_count),
            top4_rate=_ratio(TraitStatQueryTable.top4_count, TraitStatQueryTable.outcome_count),
            win_rate=_ratio(TraitStatQueryTable.win_count, TraitStatQueryTable.outcome_count),
            pick_rate=_ratio(TraitStatQueryTable.games, literal(universe)),
            universe_games=universe,
        )
    )
    unit_denominator = (
        select(UnitStatQueryTable.games)
        .where(
            UnitStatQueryTable.scope_id == UnitLoadoutStatQueryTable.scope_id,
            UnitStatQueryTable.unit_name == UnitLoadoutStatQueryTable.unit_name,
            UnitStatQueryTable.star_level == UnitLoadoutStatQueryTable.star_level,
        )
        .correlate(UnitLoadoutStatQueryTable)
        .scalar_subquery()
    )
    session.execute(
        update(UnitLoadoutStatQueryTable)
        .where(UnitLoadoutStatQueryTable.scope_id == scope.scope_id)
        .values(
            avg_placement=_ratio(
                UnitLoadoutStatQueryTable.placement_sum,
                UnitLoadoutStatQueryTable.outcome_count,
            ),
            top4_rate=_ratio(UnitLoadoutStatQueryTable.top4_count, UnitLoadoutStatQueryTable.outcome_count),
            win_rate=_ratio(UnitLoadoutStatQueryTable.win_count, UnitLoadoutStatQueryTable.outcome_count),
            unit_boards=func.coalesce(unit_denominator, 0),
            loadout_pick_rate=_ratio(UnitLoadoutStatQueryTable.boards, unit_denominator),
        )
    )
    scope.status = "ready"
    scope.last_success_at = utc_now()
    scope.last_error_at = None
    scope.last_error_details = None


def _eligible_unprocessed_ids(
    session: Session,
    scope: AnalysisScope,
    match_ids: Sequence[str],
) -> list[str]:
    unique_ids = list(dict.fromkeys(str(match_id) for match_id in match_ids if match_id))
    if not unique_ids:
        return []
    eligible = set(
        session.scalars(
            select(RawMatch.match_id).where(
                RawMatch.match_id.in_(unique_ids),
                _scope_match_clause(scope),
            )
        )
    )
    processed = set(
        session.scalars(
            select(AnalysisProcessedMatch.match_id).where(
                AnalysisProcessedMatch.scope_id == scope.scope_id,
                AnalysisProcessedMatch.match_id.in_(eligible),
            )
        )
    )
    return [match_id for match_id in unique_ids if match_id in eligible - processed]


def _append_match_projection(
    session: Session,
    scope: AnalysisScope,
    match_ids: Sequence[str],
) -> None:
    if not match_ids:
        return
    existing = set(
        session.execute(
            select(Match.match_id, Match.puuid).where(Match.match_id.in_(match_ids))
        ).all()
    )
    rows = session.execute(
        select(RawMatch, PlayerBoard.puuid)
        .join(PlayerBoard, PlayerBoard.match_id == RawMatch.match_id)
        .where(RawMatch.match_id.in_(match_ids), _scope_match_clause(scope))
    ).all()
    for raw, puuid in rows:
        if (raw.match_id, puuid) in existing:
            continue
        session.add(
            Match(
                match_id=raw.match_id,
                puuid=puuid,
                region=raw.region,
                platform=raw.platform,
                game_datetime=raw.game_datetime,
                game_length=raw.game_length,
                game_version=raw.game_version,
                tft_set_number=raw.tft_set_number,
                tft_set_core_name=raw.tft_set_core_name,
                ingested_at=raw.ingested_at,
            )
        )


def _replace_match_projection(session: Session, scope: AnalysisScope) -> int:
    session.execute(delete(Match))
    columns = [
        "match_id",
        "puuid",
        "region",
        "platform",
        "game_datetime",
        "game_length",
        "game_version",
        "tft_set_number",
        "tft_set_core_name",
        "ingested_at",
    ]
    source = (
        select(
            RawMatch.match_id,
            PlayerBoard.puuid,
            RawMatch.region,
            RawMatch.platform,
            RawMatch.game_datetime,
            RawMatch.game_length,
            RawMatch.game_version,
            RawMatch.tft_set_number,
            RawMatch.tft_set_core_name,
            RawMatch.ingested_at,
        )
        .join(PlayerBoard, PlayerBoard.match_id == RawMatch.match_id)
        .where(_scope_match_clause(scope))
    )
    session.execute(insert(Match).from_select(columns, source))
    session.flush()
    return int(session.scalar(select(func.count()).select_from(Match)) or 0)


def _process_ids_locked(
    session: Session,
    scope: AnalysisScope,
    match_ids: Sequence[str],
    *,
    recalculate: bool,
) -> dict[str, int]:
    pending = _eligible_unprocessed_ids(session, scope, match_ids)
    if not pending:
        if recalculate:
            _recalculate_published_metrics(session, scope)
            fact_validation(session, scope)
        return {"processed_matches": 0, "boards": 0}
    excluded_item_names = discard_ambiguous_item_stats(session, scope)
    rows_by_model, fact_rows_by_model, board_counts = _contribution_rows(
        session, scope, pending, excluded_item_names
    )
    fact_build = _fact_build(session, scope.scope_id)
    if not recalculate:
        scope.status = "building"
        fact_build.status = "incomplete"
        fact_build.updated_at = utc_now()
        fact_build.ready_at = None
    _insert_fact_rows(session, fact_rows_by_model)
    _upsert_additive(
        session,
        UnitStatQueryTable,
        rows_by_model[UnitStatQueryTable],
        ("games", "placement_sum", "outcome_count", "top4_count", "win_count"),
        max_fields=("cost",),
    )
    validate_item_stat_metadata(
        session,
        rows_by_model[ItemStatQueryTable],
    )
    _upsert_additive(
        session,
        ItemStatQueryTable,
        rows_by_model[ItemStatQueryTable],
        ("holds", "boards", "placement_sum", "outcome_count", "top4_count", "win_count"),
    )
    _upsert_additive(
        session,
        TraitStatQueryTable,
        rows_by_model[TraitStatQueryTable],
        ("games", "placement_sum", "outcome_count", "top4_count", "win_count"),
    )
    _upsert_additive(
        session,
        UnitLoadoutStatQueryTable,
        rows_by_model[UnitLoadoutStatQueryTable],
        ("boards", "placement_sum", "outcome_count", "top4_count", "win_count"),
    )
    session.add_all(
        AnalysisProcessedMatch(
            scope_id=scope.scope_id,
            match_id=match_id,
            board_count=board_counts[match_id],
        )
        for match_id in pending
    )
    _append_match_projection(session, scope, pending)
    session.flush()
    if recalculate:
        _recalculate_published_metrics(session, scope)
        fact_validation(session, scope)
    return {
        "processed_matches": len(pending),
        "boards": sum(board_counts.values()),
    }


def _record_scope_error(session: Session, scope_id: int, exc: BaseException) -> None:
    try:
        scope = session.get(AnalysisScope, scope_id)
        if scope is None:
            return
        if scope.status != "dirty":
            scope.status = "error"
        scope.last_error_at = utc_now()
        scope.last_error_details = str(exc)[:4000]
        fact_build = session.get(AnalysisFactBuild, scope_id)
        if fact_build is not None:
            fact_build.status = "dirty"
            fact_build.updated_at = utc_now()
            fact_build.last_error_at = utc_now()
            fact_build.last_error_details = str(exc)[:4000]
        session.commit()
    except Exception:  # noqa: BLE001 - preserve the original analytics error.
        session.rollback()
        logger.exception("failed to persist analytics scope error scope_id=%s", scope_id)


def process_match_batch(
    session: Session,
    match_ids: Sequence[str],
    *,
    scope: AnalysisScope | None = None,
    patch: str | None = None,
    finalize: bool = True,
) -> dict[str, int]:
    """Idempotently add matches, optionally deferring publication validation."""
    if scope is None:
        scope = resolve_analysis_scope(session, patch=patch)
    if scope is None:
        session.commit()
        return {"processed_matches": 0, "boards": 0}
    scope_id = scope.scope_id
    session.commit()  # Persist scope selection before the isolated analytics txn.
    try:
        scope = session.get(AnalysisScope, scope_id)
        if scope is None:
            raise RuntimeError(f"analysis scope {scope_id} disappeared")
        if scope.status == "dirty":
            raise RuntimeError(
                f"analysis scope {scope_id} is dirty and requires a full rebuild"
            )
        with _scope_transaction_lock(session, scope_id):
            result = _process_ids_locked(
                session,
                scope,
                list(match_ids),
                recalculate=finalize,
            )
            session.commit()
            return result
    except Exception as exc:
        session.rollback()
        _record_scope_error(session, scope_id, exc)
        raise


def finalize_query_tables(
    session: Session,
    *,
    scope: AnalysisScope | None = None,
    patch: str | None = None,
) -> dict[str, int]:
    """Publish metrics and validate facts once after incremental batches."""
    if scope is None:
        scope = resolve_analysis_scope(session, patch=patch)
    if scope is None:
        session.commit()
        return {"processed_matches": 0, "boards": 0}
    scope_id = scope.scope_id
    session.commit()
    try:
        scope = session.get(AnalysisScope, scope_id)
        if scope is None:
            raise RuntimeError(f"analysis scope {scope_id} disappeared")
        if scope.status == "dirty":
            raise RuntimeError(
                f"analysis scope {scope_id} is dirty and requires a full rebuild"
            )
        with _scope_transaction_lock(session, scope_id):
            _recalculate_published_metrics(session, scope)
            validation = fact_validation(session, scope, require_ready=True)
            session.commit()
        source = validation["source"]
        return {
            "processed_matches": int(source["processed_matches"]),
            "boards": int(source["boards"]),
        }
    except Exception as exc:
        session.rollback()
        _record_scope_error(session, scope_id, exc)
        raise


def find_unprocessed_match_ids(
    session: Session,
    *,
    scope: AnalysisScope | None = None,
    limit: int = 500,
) -> list[str]:
    """Return scoped raw matches absent from the processed ledger."""
    scope = scope or active_analysis_scope(session) or resolve_analysis_scope(session)
    if scope is None:
        return []
    statement = (
        select(RawMatch.match_id)
        .outerjoin(
            AnalysisProcessedMatch,
            and_(
                AnalysisProcessedMatch.scope_id == scope.scope_id,
                AnalysisProcessedMatch.match_id == RawMatch.match_id,
            ),
        )
        .where(
            _scope_match_clause(scope),
            AnalysisProcessedMatch.match_id.is_(None),
        )
        .order_by(RawMatch.game_datetime, RawMatch.match_id)
        .limit(max(int(limit), 1))
    )
    return list(session.scalars(statement))


def _count_unprocessed_matches(session: Session, scope: AnalysisScope) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(RawMatch)
            .outerjoin(
                AnalysisProcessedMatch,
                and_(
                    AnalysisProcessedMatch.scope_id == scope.scope_id,
                    AnalysisProcessedMatch.match_id == RawMatch.match_id,
                ),
            )
            .where(
                _scope_match_clause(scope),
                AnalysisProcessedMatch.match_id.is_(None),
            )
        )
        or 0
    )


def catch_up_query_tables(
    session: Session,
    *,
    batch_size: int = 500,
    max_matches: int | None = None,
    patch: str | None = None,
    finalize: bool = True,
) -> dict[str, int]:
    """Process ledger-missing matches and publish once after all batches."""
    scope = resolve_analysis_scope(session, patch=patch)
    if scope is None:
        session.commit()
        return {"processed_matches": 0, "boards": 0, "remaining_matches": 0}
    session.commit()
    total_matches = 0
    total_boards = 0
    while max_matches is None or total_matches < max_matches:
        remaining_capacity = batch_size
        if max_matches is not None:
            remaining_capacity = min(remaining_capacity, max_matches - total_matches)
        ids = find_unprocessed_match_ids(
            session,
            scope=session.get(AnalysisScope, scope.scope_id),
            limit=remaining_capacity,
        )
        session.rollback()  # End the read snapshot before the processing transaction.
        if not ids:
            break
        result = process_match_batch(
            session,
            ids,
            scope=session.get(AnalysisScope, scope.scope_id),
            finalize=False,
        )
        total_matches += result["processed_matches"]
        total_boards += result["boards"]
    if finalize:
        finalize_query_tables(
            session,
            scope=session.get(AnalysisScope, scope.scope_id),
        )
    current_scope = session.get(AnalysisScope, scope.scope_id)
    if current_scope is None:
        raise RuntimeError(f"analysis scope {scope.scope_id} disappeared")
    remaining = _count_unprocessed_matches(session, current_scope)
    session.rollback()
    return {
        "processed_matches": total_matches,
        "boards": total_boards,
        "remaining_matches": remaining,
    }


def _scope_counts(session: Session, scope_id: int) -> dict[str, int]:
    return {
        model.__tablename__: int(
            session.scalar(
                select(func.count()).select_from(model).where(model.scope_id == scope_id)
            )
            or 0
        )
        for model in (
            *_AGGREGATE_MODELS,
            AnalysisBoard,
            AnalysisBoardUnitList,
            AnalysisBoardTraitList,
            AnalysisBoardUnit,
            AnalysisBoardItem,
            AnalysisBoardTrait,
        )
    }


def rebuild_query_tables(
    session: Session,
    *,
    match_ids: Sequence[str] | None = None,
    explain: bool = False,
    explain_analyze: bool = False,
    patch: str | None = None,
    batch_size: int = 500,
    finalize: bool = True,
) -> dict[str, int]:
    """Full configured-scope rebuild, or idempotent incremental update.

    ``match_ids=None`` is the explicit full rebuild interface.  Supplying IDs
    never resets aggregates and replays are no-ops by ledger design.
    """
    started = time.perf_counter()
    _normalize_field_names(session)
    _ensure_query_table_schema(session)
    scope = resolve_analysis_scope(session, patch=patch)
    if scope is None:
        session.commit()
        empty = {model.__tablename__: 0 for model in _AGGREGATE_MODELS}
        return {"matches": 0, **empty, "processed_matches": 0}
    scope_id = scope.scope_id
    session.commit()

    if match_ids is not None:
        result = process_match_batch(
            session,
            list(match_ids),
            scope=session.get(AnalysisScope, scope_id),
            finalize=finalize,
        )
        counts = _scope_counts(session, scope_id)
        match_count = int(session.scalar(select(func.count()).select_from(Match)) or 0)
        session.rollback()
        return {"matches": match_count, **counts, **result}

    try:
        scope = session.get(AnalysisScope, scope_id)
        if scope is None:
            raise RuntimeError(f"analysis scope {scope_id} disappeared")
        with _scope_transaction_lock(session, scope_id):
            scope.status = "building"
            fact_build = _fact_build(session, scope_id)
            fact_build.status = "incomplete"
            fact_build.schema_version = ANALYSIS_FACT_SCHEMA_VERSION
            fact_build.ready_at = None
            for model in _AGGREGATE_MODELS:
                session.execute(delete(model).where(model.scope_id == scope_id))
            for model in _FACT_MODELS:
                session.execute(delete(model).where(model.scope_id == scope_id))
            session.execute(
                delete(AnalysisProcessedMatch).where(
                    AnalysisProcessedMatch.scope_id == scope_id
                )
            )
            scope.universe_boards = 0
            match_count = _replace_match_projection(session, scope)
            processed = 0
            boards = 0
            batch_number = 0
            cursor: tuple[int, str] | None = None
            while True:
                page = select(RawMatch.match_id, RawMatch.game_datetime).where(
                    _scope_match_clause(scope)
                )
                if cursor is not None:
                    cursor_datetime, cursor_match_id = cursor
                    page = page.where(
                        or_(
                            RawMatch.game_datetime > cursor_datetime,
                            and_(
                                RawMatch.game_datetime == cursor_datetime,
                                RawMatch.match_id > cursor_match_id,
                            ),
                        )
                    )
                page_rows = session.execute(
                    page.order_by(RawMatch.game_datetime, RawMatch.match_id).limit(
                        max(int(batch_size), 1)
                    )
                ).all()
                if not page_rows:
                    break
                batch_number += 1
                batch = [row.match_id for row in page_rows]
                result = _process_ids_locked(
                    session,
                    scope,
                    batch,
                    recalculate=False,
                )
                processed += result["processed_matches"]
                boards += result["boards"]
                logger.info(
                    "analytics rebuild batch complete scope_id=%s batch=%d "
                    "batch_matches=%d processed_matches=%d boards=%d "
                    "transaction_pending=%s",
                    scope_id,
                    batch_number,
                    result["processed_matches"],
                    processed,
                    boards,
                    str(session.in_transaction()).lower(),
                )
                last_row = page_rows[-1]
                cursor = (int(last_row.game_datetime), str(last_row.match_id))
            _recalculate_published_metrics(session, scope)
            fact_validation(session, scope, require_ready=True)
            if explain or explain_analyze:
                _log_scope_plans(session, scope, analyze=explain_analyze)
            session.commit()
        counts = _scope_counts(session, scope_id)
        session.rollback()
        result_counts = {
            "matches": match_count,
            **counts,
            "processed_matches": processed,
            "boards": boards,
        }
        logger.info(
            "analytics rebuild finished scope_id=%s elapsed_ms=%.1f counts=%s",
            scope_id,
            (time.perf_counter() - started) * 1000,
            result_counts,
        )
        return result_counts
    except Exception as exc:
        session.rollback()
        _record_scope_error(session, scope_id, exc)
        raise


def build_match_query_table(session: Session, *, patch: str | None = None) -> int:
    """Rebuild the compatibility ``matches`` projection for the active scope."""
    _normalize_field_names(session)
    scope = resolve_analysis_scope(session, patch=patch)
    if scope is None:
        session.execute(delete(Match))
        session.commit()
        return 0
    count = _replace_match_projection(session, scope)
    session.commit()
    return count


def build_unit_query_table(
    session: Session, *, min_games: int = 1, refresh_patch: bool = True
) -> int:
    result = rebuild_query_tables(session)
    if min_games <= 1:
        return result["unit_stats"]
    scope = active_analysis_scope(session)
    return int(
        session.scalar(
            select(func.count()).select_from(UnitStatQueryTable).where(
                UnitStatQueryTable.scope_id == scope.scope_id,
                UnitStatQueryTable.games >= min_games,
            )
        )
        or 0
    )


def build_item_query_table(
    session: Session, *, min_holds: int = 1, refresh_patch: bool = True
) -> int:
    result = rebuild_query_tables(session)
    if min_holds <= 1:
        return result["item_stats"]
    scope = active_analysis_scope(session)
    return int(
        session.scalar(
            select(func.count()).select_from(ItemStatQueryTable).where(
                ItemStatQueryTable.scope_id == scope.scope_id,
                ItemStatQueryTable.holds >= min_holds,
            )
        )
        or 0
    )


def build_trait_query_table(
    session: Session, *, min_games: int = 1, refresh_patch: bool = True
) -> int:
    result = rebuild_query_tables(session)
    if min_games <= 1:
        return result["trait_stats"]
    scope = active_analysis_scope(session)
    return int(
        session.scalar(
            select(func.count()).select_from(TraitStatQueryTable).where(
                TraitStatQueryTable.scope_id == scope.scope_id,
                TraitStatQueryTable.games >= min_games,
            )
        )
        or 0
    )


def _parse_trait_code(code: str | None) -> set[tuple[str, int]]:
    """Parse legacy ``name_tier#...`` strings using the final underscore."""
    parsed: set[tuple[str, int]] = set()
    for segment in (code or "").split("#"):
        name, separator, tier_text = segment.rpartition("_")
        if not separator or not name:
            continue
        try:
            parsed.add((name, int(tier_text)))
        except ValueError:
            continue
    return parsed


def _match_set_universe_statement() -> Any:
    """Compatibility helper retained for planner/tests."""
    set_number = func.coalesce(Match.tft_set_number, 0)
    return select(set_number, func.count()).group_by(set_number)


def _unit_query_table_select(min_games: int = 1) -> Any:
    return select(UnitStatQueryTable).where(UnitStatQueryTable.games >= min_games)


def _item_query_table_select(min_holds: int = 1) -> Any:
    return select(ItemStatQueryTable).where(ItemStatQueryTable.holds >= min_holds)


def _log_scope_plans(session: Session, scope: AnalysisScope, *, analyze: bool) -> None:
    if session.get_bind().dialect.name != "postgresql":
        return
    for name, statement in (
        (
            "catch_up",
            select(RawMatch.match_id)
            .outerjoin(
                AnalysisProcessedMatch,
                and_(
                    AnalysisProcessedMatch.scope_id == scope.scope_id,
                    AnalysisProcessedMatch.match_id == RawMatch.match_id,
                ),
            )
            .where(_scope_match_clause(scope), AnalysisProcessedMatch.match_id.is_(None)),
        ),
        (
            "cohort_board_join",
            select(PlayerBoard.match_id, PlayerBoard.puuid)
            .join(RawMatch, RawMatch.match_id == PlayerBoard.match_id)
            .where(_scope_match_clause(scope)),
        ),
    ):
        sql = str(
            statement.compile(
                dialect=session.get_bind().dialect,
                compile_kwargs={"literal_binds": True},
            )
        )
        options = "ANALYZE, BUFFERS, " if analyze else ""
        rows = session.execute(text(f"EXPLAIN ({options}FORMAT TEXT) {sql}"))
        logger.info(
            "analytics plan stage=%s analyze=%s:\n%s",
            name,
            analyze,
            "\n".join(str(row[0]) for row in rows),
        )


def mark_scopes_dirty_for_matches(
    session: Session,
    match_ids: Sequence[str],
    *,
    reason: str = "normalized raw data changed after analytics processing",
) -> int:
    """Mark processed scopes dirty after an authorized raw update/delete."""
    ids = list(dict.fromkeys(match_ids))
    if not ids:
        return 0
    scope_ids = list(
        session.scalars(
            select(AnalysisProcessedMatch.scope_id)
            .where(AnalysisProcessedMatch.match_id.in_(ids))
            .distinct()
        )
    )
    if not scope_ids:
        return 0
    result = session.execute(
        update(AnalysisScope)
        .where(AnalysisScope.scope_id.in_(scope_ids))
        .values(
            status="dirty",
            last_error_at=utc_now(),
            last_error_details=reason[:4000],
        )
    )
    session.execute(
        update(AnalysisFactBuild)
        .where(AnalysisFactBuild.scope_id.in_(scope_ids))
        .values(
            status="dirty",
            updated_at=utc_now(),
            last_error_at=utc_now(),
            last_error_details=reason[:4000],
        )
    )
    return int(result.rowcount or 0)


__all__ = [
    "ANALYSIS_BOARD_NAMESPACE",
    "ANALYSIS_LOBBY_NAMESPACE",
    "AnalysisScopeIdentity",
    "active_analysis_scope",
    "anonymous_board_key",
    "anonymous_lobby_key",
    "build_item_query_table",
    "build_match_query_table",
    "build_trait_query_table",
    "build_unit_query_table",
    "catch_up_query_tables",
    "configured_queue_id",
    "current_patch",
    "find_unprocessed_match_ids",
    "fact_validation",
    "finalize_query_tables",
    "mark_scopes_dirty_for_matches",
    "process_match_batch",
    "rebuild_query_tables",
    "resolve_analysis_scope",
    "resolve_configured_scope",
]
