"""CLI to catch up AI-facing derived tables or explicitly rebuild them."""

from __future__ import annotations

import argparse
import json
from ipaddress import ip_address
import logging
from pathlib import Path
import sys
import time
from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import urlsplit

from sqlalchemy import func, inspect, text

# Add the backend src to path to import config loader
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "app" / "backend" / "src")
)
from core.config import load_config

from aws.rds import build_rds_client
from common.sql import quote_identifier
from db.build_query_tables import rebuild_query_tables as rebuild_db_query_tables
from db.build_query_tables import catch_up_query_tables
from db.models import (
    AnalysisProcessedMatch,
    AnalysisScope,
    ItemStatQueryTable,
    Match,
    TraitStatQueryTable,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
)
from db.session import database_label, db_stats, open_db

logger = logging.getLogger("tft-rebuild-tables")
DEFAULT_RDS_POLL_SECONDS = 10
DEFAULT_RDS_TIMEOUT_SECONDS = 90 * 60
DEFAULT_RDS_INSTANCE_CLASS = "db.t4g.micro"
DEFAULT_RDS_TEMP_CLASS = "db.r7g.xlarge"
_RETIRED_AGGREGATE_TABLES = ("unit_pair_stats", "trait_unit_stats")


def _drop_retired_aggregate_tables(session: Any) -> list[str]:
    """Drop obsolete derived projections during explicit maintenance rebuilds.

    Args:
        session: Maintenance database session used for the full rebuild.

    Returns:
        Physical table names removed from the target database.
    """
    inspector = inspect(session.connection())
    retired = [
        table_name
        for table_name in _RETIRED_AGGREGATE_TABLES
        if inspector.has_table(table_name)
    ]
    for table_name in retired:
        session.execute(text(f"DROP TABLE {quote_identifier(table_name)}"))
    session.commit()
    return retired

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Update the configured analysis scope using existing calculations. "
            "Use --full-rebuild to replace its derived tables from scratch."
        )
    )
    parser.add_argument(
        "--full-rebuild",
        action="store_true",
        help=(
            "Clear the configured scope's facts, aggregates, and processed-match "
            "ledger and recalculate every eligible match. Required to repair a dirty scope."
        ),
    )
    parser.add_argument(
        "--dsn",
        help="Explicit maintenance DSN override. Defaults to the configured app RDS target.",
    )
    parser.add_argument(
        "--patch",
        help=(
            "Patch to project, e.g. 16.10. Overrides patch in the "
            "[chat] config section. Defaults to that setting, then latest."
        ),
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help=(
            "Log PostgreSQL planner estimates for catch-up and normalized "
            "cohort join paths. Requires --full-rebuild."
        ),
    )
    parser.add_argument(
        "--explain-analyze",
        action="store_true",
        help=(
            "Execute and log EXPLAIN ANALYZE, BUFFERS for those diagnostic "
            "paths. Requires --full-rebuild. Use only during maintenance profiling."
        ),
    )
    parser.add_argument(
        "--rds-instance-id",
        default=None,
        help=(
            "RDS DB instance identifier to resize for this rebuild. Defaults to "
            "the instance configured by RDS_INSTANCE_ID."
        ),
    )
    parser.add_argument(
        "--upgrade-instance-class",
        default=DEFAULT_RDS_TEMP_CLASS,
        help=(
            "Temporary RDS DB instance class, such as db.r7g.xlarge. The script "
            "records the current class, waits for this class before rebuilding, "
            "then restores the original class."
        ),
    )
    parser.add_argument(
        "--rds-poll-seconds",
        type=int,
        default=DEFAULT_RDS_POLL_SECONDS,
        help="Seconds between RDS status pollws (default: %(default)s).",
    )
    parser.add_argument(
        "--rds-timeout-seconds",
        type=int,
        default=DEFAULT_RDS_TIMEOUT_SECONDS,
        help="Maximum seconds to wait for each RDS resize (default: %(default)s).",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse maintenance options and require a full rebuild for planner profiling."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if (args.explain or args.explain_analyze) and not args.full_rebuild:
        parser.error("--explain and --explain-analyze require --full-rebuild")
    return args


def _query_table_counts(session: Any) -> dict[str, int]:
    scope = (
        session.query(AnalysisScope)
        .filter(AnalysisScope.is_active.is_(True))
        .one_or_none()
    )
    scope_id = scope.scope_id if scope is not None else None

    def scoped_count(model: Any) -> int:
        if scope_id is None:
            return 0
        return int(
            session.query(func.count())
            .select_from(model)
            .filter(model.scope_id == scope_id)
            .scalar()
            or 0
        )

    return {
        "matches": int(session.query(func.count()).select_from(Match).scalar() or 0),
        "unit_stats": scoped_count(UnitStatQueryTable),
        "item_stats": scoped_count(ItemStatQueryTable),
        "trait_stats": scoped_count(TraitStatQueryTable),
        "unit_loadout_stats": scoped_count(UnitLoadoutStatQueryTable),
        "processed_matches": scoped_count(AnalysisProcessedMatch),
        "universe_boards": int(scope.universe_boards if scope is not None else 0),
    }


def _rds_instance_details(client: Any, instance_id: str) -> dict[str, Any]:
    instances = client.describe_db_instances(DBInstanceIdentifier=instance_id).get(
        "DBInstances", []
    )
    if len(instances) != 1:
        raise RuntimeError(f"RDS instance {instance_id!r} was not found uniquely.")
    return instances[0]


def _wait_for_rds_instance_class(
    client: Any,
    *,
    instance_id: str,
    target_class: str,
    poll_seconds: int,
    timeout_seconds: int,
) -> None:
    if poll_seconds <= 0:
        raise ValueError("rds_poll_seconds must be positive")
    if timeout_seconds <= 0:
        raise ValueError("rds_timeout_seconds must be positive")

    deadline = time.monotonic() + timeout_seconds
    previous_state: tuple[str | None, str | None, str | None] | None = None
    while True:
        instance = _rds_instance_details(client, instance_id)
        status = instance.get("DBInstanceStatus")
        instance_class = instance.get("DBInstanceClass")
        pending_class = (instance.get("PendingModifiedValues") or {}).get(
            "DBInstanceClass"
        )
        state = (status, instance_class, pending_class)
        if state != previous_state:
            logger.info(
                "RDS resize status instance=%s status=%s class=%s pending_class=%s target_class=%s",
                instance_id,
                status,
                instance_class,
                pending_class or "none",
                target_class,
            )
            previous_state = state
        if status == "available" and instance_class == target_class:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Timed out waiting for RDS instance "
                f"{instance_id!r} to become available as {target_class!r}; "
                f"last status={status!r}, class={instance_class!r}."
            )
        time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))


def _request_rds_instance_class(
    client: Any,
    *,
    instance_id: str,
    instance_class: str,
) -> None:
    logger.info(
        "Requesting RDS resize instance=%s target_class=%s apply_immediately=true",
        instance_id,
        instance_class,
    )
    client.modify_db_instance(
        DBInstanceIdentifier=instance_id,
        DBInstanceClass=instance_class,
        ApplyImmediately=True,
    )


def _configured_rds_instance_id() -> str:
    """Resolve the configured RDS ID, falling back to the endpoint hostname.

    RDS_INSTANCE_ID is preferred. Older local configurations may only have
    RDS_HOST, whose first DNS label normally matches the DB instance ID.
    """
    target = load_config().rds
    if target.instance_id:
        return target.instance_id
    if target.host:
        derived_id = target.host.split(".", 1)[0].strip()
        if derived_id:
            logger.warning(
                "RDS_INSTANCE_ID is unset; deriving the instance ID %r from RDS_HOST",
                derived_id,
            )
            return derived_id
    return ""


def _is_local_database_target(args: argparse.Namespace) -> bool:
    """Return whether the rebuild target is a local PostgreSQL endpoint.

    Explicit maintenance DSNs take precedence over application configuration.
    A missing host in a DSN represents a Unix-domain socket, while configured
    loopback hosts represent local PostgreSQL; neither target can be resized
    through the AWS RDS API.

    Args:
        args: Parsed rebuild command arguments.

    Returns:
        True when the target resolves to a local PostgreSQL endpoint.
    """
    explicit_dsn = getattr(args, "dsn", None)
    if explicit_dsn:
        host = urlsplit(explicit_dsn).hostname
        if not host:
            return True
    else:
        config = load_config()
        target = config.rds
        host = getattr(target, "host", "")
        if not host:
            # An explicit instance ID indicates an RDS target even when a
            # test double or incomplete configuration omits its host field.
            return not (
                getattr(args, "rds_instance_id", None)
                or getattr(target, "instance_id", "")
            )

    normalized_host = str(host).strip().lower().rstrip(".")
    if normalized_host in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ip_address(normalized_host).is_loopback
    except ValueError:
        return False


@contextmanager
def _temporary_rds_upgrade(args: argparse.Namespace) -> Iterator[None]:
    """Temporarily resize one RDS instance and restore it after the rebuild.

    This context manager deliberately requires both identifiers from the CLI;
    deriving an RDS instance ID from a database endpoint is unreliable and could
    resize an unintended instance. A process kill or host failure can still
    prevent restoration, so the original class is always logged before change.
    """
    upgrade_class = getattr(args, "upgrade_instance_class", None)
    instance_id = getattr(args, "rds_instance_id", None)
    if _is_local_database_target(args):
        logger.info("Local PostgreSQL target detected; skipping RDS resize")
        yield
        return
    if upgrade_class and not instance_id:
        instance_id = _configured_rds_instance_id()
    if not upgrade_class:
        yield
        return
    if not instance_id:
        raise ValueError(
            "An RDS instance ID is required: provide --rds-instance-id or configure "
            "RDS_INSTANCE_ID."
        )

    poll_seconds = int(getattr(args, "rds_poll_seconds", DEFAULT_RDS_POLL_SECONDS))
    timeout_seconds = int(
        getattr(args, "rds_timeout_seconds", DEFAULT_RDS_TIMEOUT_SECONDS)
    )
    client = build_rds_client()
    original_class = _rds_instance_details(client, instance_id).get("DBInstanceClass")
    if not original_class:
        raise RuntimeError(f"RDS instance {instance_id!r} did not report DBInstanceClass.")
    changed = original_class != upgrade_class
    logger.info(
        "RDS rebuild resize plan instance=%s original_class=%s upgrade_class=%s",
        instance_id,
        original_class,
        upgrade_class,
    )
    if not changed:
        logger.info("RDS rebuild resize skipped; instance already uses %s", upgrade_class)
        yield
        return

    _request_rds_instance_class(
        client,
        instance_id=instance_id,
        instance_class=upgrade_class,
    )
    try:
        _wait_for_rds_instance_class(
            client,
            instance_id=instance_id,
            target_class=upgrade_class,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        logger.info(
            "RDS resize complete instance=%s class=%s; starting rebuild",
            instance_id,
            upgrade_class,
        )
        yield
    finally:
        logger.info(
            "Restoring RDS instance=%s class=%s after rebuild",
            instance_id,
            original_class,
        )
        _request_rds_instance_class(
            client,
            instance_id=instance_id,
            instance_class=original_class,
        )
        _wait_for_rds_instance_class(
            client,
            instance_id=instance_id,
            target_class=original_class,
            poll_seconds=poll_seconds,
            timeout_seconds=timeout_seconds,
        )
        logger.info(
            "RDS restore complete instance=%s class=%s",
            instance_id,
            original_class,
        )


def rebuild_tables(args: argparse.Namespace) -> dict[str, Any]:
    """Catch up the configured scope, or replace it when explicitly requested."""
    full_rebuild = bool(getattr(args, "full_rebuild", False))
    mode = "full_rebuild" if full_rebuild else "catch_up"
    instance_id = (
        None
        if _is_local_database_target(args)
        else getattr(args, "rds_instance_id", None) or _configured_rds_instance_id()
    )
    args = argparse.Namespace(**{**vars(args), "rds_instance_id": instance_id})
    with _temporary_rds_upgrade(args):
        session = open_db(args.dsn)
        label = database_label(args.dsn)
        try:
            logger.info("Database: %s", label)
            logger.info("Query table update mode: %s", mode)
            if full_rebuild:
                retired = _drop_retired_aggregate_tables(session)
                if retired:
                    logger.info("Removed retired aggregate tables: %s", retired)
            raw_before = db_stats(session)
            query_before = _query_table_counts(session)
            logger.info(
                "Before: raw_matches=%s participants=%s query_tables=%s",
                raw_before["matches"],
                raw_before["participants"],
                query_before,
            )
            started = time.perf_counter()
            options: dict[str, Any] = {}
            if getattr(args, "patch", None) is not None:
                options["patch"] = args.patch
            if full_rebuild:
                options.update(
                    explain=bool(getattr(args, "explain", False)),
                    explain_analyze=bool(getattr(args, "explain_analyze", False)),
                )
                counts = rebuild_db_query_tables(session, **options)
            else:
                progress = catch_up_query_tables(session, **options)
                # Keep aggregate totals while reporting only this run's ledger additions.
                counts = {**_query_table_counts(session), **progress}
            elapsed = time.perf_counter() - started
            result = {
                "database": label,
                "mode": mode,
                "elapsed_seconds": round(elapsed, 3),
                "before": {
                    "raw_matches": raw_before["matches"],
                    "raw_participants": raw_before["participants"],
                    "raw_item_metadata": raw_before.get("item_metadata", 0),
                    **query_before,
                },
                "counts": counts,
                **counts,
            }
            logger.info(
                "Updated query tables in %.1fs. mode=%s counts=%s",
                elapsed,
                mode,
                counts,
            )
            return result
        finally:
            session.close()


def main(argv: list[str] | None = None) -> None:
    load_config()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    for noisy in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.orm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    result = rebuild_tables(parse_args(argv))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
