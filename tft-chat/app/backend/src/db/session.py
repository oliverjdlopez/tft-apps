"""SQLAlchemy session and database lifecycle helpers."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, func, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, attributes, sessionmaker

from aws.rds import generate_rds_auth_token, rds_connection_info, sync_rds_security_group_ip
from common.sql import quote_identifier
from core.config import (
    DatabasePurpose,
    DatabaseTarget,
    resolve_database_target as resolve_configured_database_target,
)

from .models import (
    AnalysisProcessedMatch,
    AnalysisScope,
    AnalysisFactBuild,
    Base,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    PlayerBoard,
    RawMatch,
    RUNTIME_MODELS,
    UnitItem,
    utc_now,
)
from .utils import _looks_like_postgres, _sqlalchemy_url

CONNECT_TIMEOUT_SECONDS = 15
POOL_TIMEOUT_SECONDS = 15

logger = logging.getLogger("tft.analysis.db")


_NORMALIZED_RAW_TYPES = (RawMatch, PlayerBoard, BoardUnit, UnitItem, BoardTrait)


@event.listens_for(Session, "before_flush")
def _mark_analytics_dirty_for_raw_mutations(
    session: Session,
    _flush_context: Any,
    _instances: Any,
) -> None:
    """Require a full rebuild after any already-processed raw mutation.

    Append-only ingestion creates new objects whose match ids are absent from
    the ledger, so it is naturally a no-op here.  Updates, child additions, and
    deletes for processed matches mark every affected scope dirty before
    cascading deletes can remove ledger evidence.
    """
    candidates = set(session.new) | set(session.dirty) | set(session.deleted)
    match_ids = {
        str(match_id)
        for obj in candidates
        if isinstance(obj, _NORMALIZED_RAW_TYPES)
        and (match_id := getattr(obj, "match_id", None))
        and (
            obj in session.new
            or obj in session.deleted
            or session.is_modified(obj, include_collections=False)
        )
    }
    metadata_scope_keys = {
        (obj.patch, obj.tft_set_number)
        for obj in candidates
        if isinstance(obj, ItemMetadata)
        and obj not in session.new
        and (
            obj in session.deleted
            or session.is_modified(obj, include_collections=False)
        )
    }
    if not match_ids and not metadata_scope_keys:
        return
    connection = session.connection()
    scope_ids = set(
        connection.scalars(
            select(AnalysisProcessedMatch.scope_id)
            .where(AnalysisProcessedMatch.match_id.in_(match_ids))
            .distinct()
        )
    ) if match_ids else set()
    for patch, tft_set_number in metadata_scope_keys:
        scope_ids.update(
            connection.scalars(
                select(AnalysisScope.scope_id).where(
                    AnalysisScope.patch == patch,
                    AnalysisScope.tft_set_number == tft_set_number,
                )
            )
        )
    if scope_ids:
        marked_at = utc_now()
        connection.execute(
            update(AnalysisScope)
            .where(AnalysisScope.scope_id.in_(scope_ids))
            .values(
                status="dirty",
                last_error_at=marked_at,
                last_error_details="normalized raw data changed after processing",
            )
        )
        connection.execute(
            update(AnalysisFactBuild)
            .where(AnalysisFactBuild.scope_id.in_(scope_ids))
            .values(
                status="dirty",
                updated_at=marked_at,
                last_error_at=marked_at,
                last_error_details="normalized raw data changed after processing",
            )
        )
        for obj in session.identity_map.values():
            if isinstance(obj, AnalysisScope) and obj.scope_id in scope_ids:
                attributes.set_committed_value(obj, "status", "dirty")
                attributes.set_committed_value(obj, "last_error_at", marked_at)
                attributes.set_committed_value(
                    obj,
                    "last_error_details",
                    "normalized raw data changed after processing",
                )
            if isinstance(obj, AnalysisFactBuild) and obj.scope_id in scope_ids:
                attributes.set_committed_value(obj, "status", "dirty")
                attributes.set_committed_value(obj, "updated_at", marked_at)
                attributes.set_committed_value(obj, "last_error_at", marked_at)
                attributes.set_committed_value(
                    obj,
                    "last_error_details",
                    "normalized raw data changed after processing",
                )


@dataclass
class AnalysisCallState:
    """Private per-tool timing state propagated into the database worker."""

    tool: str
    call_id: str
    started_at: float = field(default_factory=time.monotonic)
    acquire_started_at: float | None = None
    acquired_at: float | None = None
    query_started_at: float | None = None
    query_finished_at: float | None = None
    checkouts: int = 0
    checkins: int = 0
    cancellation_requested: bool = False
    outcome_override: str | None = None


_ANALYSIS_CALL: contextvars.ContextVar[AnalysisCallState | None] = contextvars.ContextVar(
    "tft_analysis_call", default=None
)


def set_analysis_call(state: AnalysisCallState | None) -> contextvars.Token[Any]:
    return _ANALYSIS_CALL.set(state)


def reset_analysis_call(token: contextvars.Token[Any]) -> None:
    _ANALYSIS_CALL.reset(token)


def current_analysis_call() -> AnalysisCallState | None:
    return _ANALYSIS_CALL.get()


_DATABASE_TARGET_OVERRIDE: contextvars.ContextVar[DatabaseTarget | None] = contextvars.ContextVar(
    "tft_database_target_override", default=None
)


def resolve_database_target(
    purpose: DatabasePurpose = "app", explicit_dsn: Path | str | None = None
) -> DatabaseTarget:
    """Resolve a typed target; explicit DSNs are maintenance-only overrides."""
    # Keep a narrow positional-D​​SN bridge for existing maintenance scripts while
    # making the typed purpose form the canonical API.
    if purpose not in {"app", "eval", "test"}:
        explicit_dsn = purpose  # type: ignore[assignment]
        purpose = "app"
    if explicit_dsn is None:
        override = _DATABASE_TARGET_OVERRIDE.get()
        if override is not None:
            return override
    value = None if explicit_dsn is None else str(explicit_dsn)
    return resolve_configured_database_target(purpose, value)


@contextlib.contextmanager
def database_target_override(target: DatabaseTarget | Path | str | None):
    """Temporarily scope database consumers to a target without env mutation."""
    if target is None:
        yield
        return
    resolved = target if isinstance(target, DatabaseTarget) else resolve_database_target("eval", target)
    token = _DATABASE_TARGET_OVERRIDE.set(resolved)
    try:
        yield
    finally:
        _DATABASE_TARGET_OVERRIDE.reset(token)


def _create_engine(target: DatabaseTarget | Path | str) -> Engine:
    """Create an engine, injecting a fresh RDS IAM token per physical connection."""
    if not isinstance(target, DatabaseTarget):
        target = resolve_database_target("app", target)
    url = _sqlalchemy_url(target.connect_url)
    options: dict[str, Any] = {"pool_timeout": POOL_TIMEOUT_SECONDS}
    if _looks_like_postgres(target.connect_url):
        options["connect_args"] = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    engine = create_engine(url, **options)
    _instrument_pool(engine)
    if target.auth_mode in {"iam", "password"}:
        info = rds_connection_info(target)

        @event.listens_for(engine, "do_connect")
        def _provide_rds_token(dialect, conn_rec, cargs, cparams):  # type: ignore[no-untyped-def]
            # Tokens expire after ~15 min, so mint one for every new connection.
            # Refresh the developer-machine ingress rule at the same boundary so
            # long-running processes survive local public-IP changes.
            sync_rds_security_group_ip(target=target)
            if target.auth_mode == "iam":
                cparams["password"] = generate_rds_auth_token(info)
                cparams.setdefault("sslmode", "require")

    return engine


def pool_state(engine: Engine) -> dict[str, int | None]:
    """Return a credential-free pool snapshot for diagnostics and tests."""
    pool = getattr(engine, "pool", None)
    if pool is None:
        return {"size": None, "checked_out": None, "overflow": None, "available": None}

    def value(name: str) -> int | None:
        member = getattr(pool, name, None)
        if member is None:
            return None
        try:
            return int(member() if callable(member) else member)
        except (TypeError, ValueError, NotImplementedError):
            return None

    size = value("size")
    checked_out = value("checkedout")
    overflow = max(value("overflow") or 0, 0)
    checked_in = value("checkedin")
    max_overflow = getattr(pool, "_max_overflow", None)
    if size is not None and checked_out is not None and isinstance(max_overflow, int):
        available = (
            None
            if max_overflow < 0
            else max(size + max_overflow - checked_out, 0)
        )
    else:
        available = checked_in
    return {
        "size": size,
        "checked_out": checked_out,
        "overflow": overflow,
        "available": available,
    }


def _pool_log(event_name: str, engine: Engine, **extra: Any) -> None:
    state = _ANALYSIS_CALL.get()
    if state is None:
        return
    payload = {
        "event": event_name,
        "tool": state.tool,
        "call_id": state.call_id,
        **pool_state(engine),
        **extra,
    }
    logger.info("analysis_pool %s", json.dumps(payload, sort_keys=True))


def _instrument_pool(engine: Engine) -> None:
    """Attach credential- and query-free lifecycle logging to one engine pool."""

    @event.listens_for(engine, "connect")
    def _connect(_dbapi_connection, _connection_record):  # type: ignore[no-untyped-def]
        _pool_log("connect", engine)

    @event.listens_for(engine, "checkout")
    def _checkout(_dbapi_connection, connection_record, _proxy):  # type: ignore[no-untyped-def]
        now = time.monotonic()
        state = _ANALYSIS_CALL.get()
        connection_record.info["analysis_checked_out_at"] = now
        connection_record.info["analysis_owner"] = (
            (state.tool, state.call_id) if state is not None else None
        )
        if state is not None:
            state.checkouts += 1
            state.acquired_at = now
            wait_ms = max(0.0, (now - (state.acquire_started_at or now)) * 1000)
            _pool_log("checkout", engine, acquisition_ms=round(wait_ms, 3))
            if wait_ms > 1000:
                logger.warning(
                    "analysis_pool_slow_checkout %s",
                    json.dumps(
                        {"tool": state.tool, "call_id": state.call_id, "acquisition_ms": round(wait_ms, 3)},
                        sort_keys=True,
                    ),
                )

    @event.listens_for(engine, "checkin")
    def _checkin(_dbapi_connection, connection_record):  # type: ignore[no-untyped-def]
        now = time.monotonic()
        started = connection_record.info.pop("analysis_checked_out_at", None)
        owner = connection_record.info.pop("analysis_owner", None)
        held_ms = max(0.0, (now - started) * 1000) if started is not None else 0.0
        state = _ANALYSIS_CALL.get()
        if state is not None and owner == (state.tool, state.call_id):
            state.checkins += 1
        _pool_log("checkin", engine, checked_out_ms=round(held_ms, 3))
        if owner is not None and held_ms > 5000:
            tool, call_id = owner
            logger.warning(
                "analysis_pool_long_checkout %s",
                json.dumps(
                    {"tool": tool, "call_id": call_id, "checked_out_ms": round(held_ms, 3)},
                    sort_keys=True,
                ),
            )

    @event.listens_for(engine, "invalidate")
    def _invalidate(_dbapi_connection, _connection_record, _exception):  # type: ignore[no-untyped-def]
        _pool_log("invalidate", engine)


def database_label(path_or_dsn: DatabaseTarget | Path | str | None = None) -> str:
    if isinstance(path_or_dsn, DatabaseTarget):
        return path_or_dsn.credential_safe_url
    return resolve_database_target("app", path_or_dsn).credential_safe_url


# Default PostgreSQL schema all project tables live in.
TABLE_SCHEMA = "public"

_ENGINES: dict[str, Engine] = {}
_SCHEMA_READY: set[str] = set()
_ENGINE_STATE_LOCK = threading.RLock()


def _rename_table_sql(old_name: str, new_name: str) -> Any:
    table = f"{quote_identifier(TABLE_SCHEMA)}.{quote_identifier(old_name)}"
    return text(f"ALTER TABLE {table} RENAME TO {quote_identifier(new_name)}")


def migrate_unit_cost_columns(
    bind: Any,
    *,
    schema: str | None = TABLE_SCHEMA,
) -> int:
    """Rename legacy zero-based rarity columns and normalize them to shop cost."""
    inspection_target = bind.connection() if isinstance(bind, Session) else bind
    pending = _legacy_unit_cost_tables(inspection_target, schema=schema)
    if not pending:
        return 0

    dialect = getattr(inspection_target, "dialect", None)
    if dialect is not None and dialect.name == "postgresql":
        bind.execute(
            text(
                "SELECT pg_advisory_xact_lock("
                "hashtext('chat_tft_unit_cost_migration'))"
            )
        )
        # Another process may have completed the migration while this one
        # waited for the lock. Inspect again on the locked connection.
        pending = _legacy_unit_cost_tables(inspection_target, schema=schema)

    for table_name in pending:
        table = quote_identifier(table_name)
        if schema:
            table = f"{quote_identifier(schema)}.{table}"
        bind.execute(
            text(
                f"ALTER TABLE {table} RENAME COLUMN "
                f"{quote_identifier('rarity')} TO {quote_identifier('cost')}"
            )
        )
        bind.execute(
            text(
                f"UPDATE {table} SET {quote_identifier('cost')} = "
                f"{quote_identifier('cost')} + 1 "
                f"WHERE {quote_identifier('cost')} IS NOT NULL"
            )
        )
    return len(pending)


def _legacy_unit_cost_tables(
    inspection_target: Any,
    *,
    schema: str | None,
) -> list[str]:
    inspector = inspect(inspection_target)
    pending: list[str] = []
    for table_name in ("player_units", "unit_stats"):
        if not inspector.has_table(table_name, schema=schema):
            continue
        columns = {
            column["name"]
            for column in inspector.get_columns(table_name, schema=schema)
        }
        if "rarity" in columns and "cost" in columns:
            raise RuntimeError(
                f"{table_name} contains both legacy `rarity` and current `cost`; "
                "resolve the partial migration before startup."
            )
        if "rarity" in columns:
            pending.append(table_name)
    return pending


def _prepare_schema_names(engine: Engine) -> None:
    """Finish safe legacy column normalization before creating v2 tables.

    Table-name cutover is intentionally handled only by the maintenance-window
    relational migration; startup must never guess whether ``matches`` is raw
    or the compatibility projection.
    """
    with engine.begin() as conn:
        migrate_unit_cost_columns(conn)


def _create_runtime_schema(engine: Engine) -> None:
    Base.metadata.create_all(
        engine,
        tables=[model.__table__ for model in RUNTIME_MODELS],
    )


def _ensure_model_indexes(engine: Engine) -> None:
    """Create missing ORM-declared indexes on existing tables."""
    with engine.begin() as conn:
        inspector = inspect(conn)
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name, schema=table.schema):
                continue
            for index in table.indexes:
                index.create(bind=conn, checkfirst=True)


def engine_for(target: DatabaseTarget | Path | str | None = None, *, purpose: DatabasePurpose = "app") -> Engine:
    """Return a process-cached engine for *target*, building it on first use.

    One engine (and its connection pool) is shared per database for the life of
    the process. The RDS IAM token is still minted per physical connection via
    the ``do_connect`` listener in :func:`_create_engine`, so caching the engine
    is safe and keeps the pool warm.
    """
    resolved = target if isinstance(target, DatabaseTarget) else resolve_database_target(purpose, target)
    cache_key = f"{resolved.purpose}:{resolved.connect_url}"
    with _ENGINE_STATE_LOCK:
        engine = _ENGINES.get(cache_key)
        if engine is None:
            engine = _create_engine(resolved)
            _ENGINES[cache_key] = engine
        return engine


def open_db(
    path: DatabaseTarget | Path | str | None = None,
    *,
    purpose: DatabasePurpose = "app",
    ensure_schema: bool = True,
    create_schema: Any | None = None,
) -> Session:
    """Open an ORM session on the configured PostgreSQL database.

    The engine is cached per target, so closing the returned session returns its
    connection to the pool rather than tearing the pool down. Schema is created
    once per target; ``create_schema`` defaults to ``Base.metadata.create_all``
    and stays injectable for tests or one-off maintenance scripts.
    """
    target = path if isinstance(path, DatabaseTarget) else resolve_database_target(purpose, path)
    engine = engine_for(target)
    if ensure_schema:
        with _ENGINE_STATE_LOCK:
            schema_key = f"{target.purpose}:{target.connect_url}"
            if schema_key not in _SCHEMA_READY:
                _prepare_schema_names(engine)
                if create_schema is None:
                    _create_runtime_schema(engine)
                else:
                    create_schema(engine)
                _ensure_model_indexes(engine)
                _SCHEMA_READY.add(schema_key)
    return sessionmaker(bind=engine, expire_on_commit=False)()


async def run_db(fn, *args, **kwargs):  # type: ignore[no-untyped-def]
    """Run a synchronous database function from async tool code."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def reset_db(path: DatabaseTarget | Path | str | None = None, *, purpose: DatabasePurpose = "app") -> None:
    target = path if isinstance(path, DatabaseTarget) else resolve_database_target(purpose, path)
    engine = engine_for(target)
    with _ENGINE_STATE_LOCK:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        _ensure_model_indexes(engine)
        _SCHEMA_READY.add(f"{target.purpose}:{target.connect_url}")


def db_stats(session: Session) -> dict[str, Any]:
    """Summarize normalized raw matches and participant boards."""

    match_count_expr = func.count(RawMatch.match_id)
    matches_count = session.query(match_count_expr).scalar() or 0
    participants_count = (
        session.query(func.count()).select_from(PlayerBoard).scalar() or 0
    )

    def grouped(column: Any, label: str) -> list[dict[str, Any]]:
        rows = (
            session.query(column.label(label), func.count().label("matches"))
            .group_by(column)
            .order_by(func.count().desc())
            .all()
        )
        return [{label: key, "matches": int(count)} for key, count in rows]

    by_set_rows = (
        session.query(
            RawMatch.tft_set_number.label("set_number"),
            match_count_expr.label("matches"),
        )
        .group_by(RawMatch.tft_set_number)
        .order_by(RawMatch.tft_set_number.desc())
        .all()
    )
    latest = session.query(func.max(RawMatch.game_datetime)).scalar()
    return {
        "matches": int(matches_count),
        "participants": int(participants_count),
        "by_patch": grouped(RawMatch.patch, "patch"),
        "by_region": grouped(RawMatch.region, "region"),
        "by_queue": grouped(RawMatch.queue_id, "queue_id"),
        "by_set": [
            {"set_number": set_number, "matches": int(count)}
            for set_number, count in by_set_rows
        ],
        "latest_match_at": latest,
    }
