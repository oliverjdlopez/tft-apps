#!/usr/bin/env python3
"""Publish a validated, serving-ready RDS database for one TFT scope.

The source database is left untouched. The configured patch/queue/set raw
graph is copied from one consistent snapshot, query tables are rebuilt on the
new instance, and connection metadata is reported only after validation.

Example::

    uv run tft-freeze-patch-db 10.5 \\
        --master-user-password "$RDS_PASSWORD"

The target RDS instance identifier for that command is
``chat_tft_patch_10_5``.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import and_, exists, func, insert, select, text
from sqlalchemy.orm import Session

# Make this script runnable directly from a checkout as well as through its
# installed console command.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "backend" / "src"))

from aws.rds import build_rds_client  # noqa: E402
from core.config import load_config  # noqa: E402
from db.build_query_tables import (  # noqa: E402
    AnalysisScopeIdentity,
    rebuild_query_tables,
    resolve_configured_scope,
)
from db.models import (  # noqa: E402
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    PlayerBoard,
    RawMatch,
    UnitItem,
)
from db.session import database_label, open_db, resolve_database_target  # noqa: E402
from db.validation import validate_patch_publication  # noqa: E402


logger = logging.getLogger("tft-freeze-patch-db")
DEFAULT_DATABASE_NAME = "chat_tft"
DEFAULT_BATCH_SIZE = 1_000
_PATCH_RE = re.compile(r"^\d+\.\d+$")

# Copy parents before children so all normalized foreign keys remain valid.
_PATCH_TABLES: tuple[type[Any], ...] = (
    RawMatch,
    ItemMetadata,
    PlayerBoard,
    BoardUnit,
    UnitItem,
    BoardTrait,
)


@dataclass(frozen=True)
class FreezeOptions:
    patch: str
    source_instance_id: str = field(default_factory=lambda: load_config().rds.instance_id)
    source_dsn: str | None = None
    master_user_password: str | None = None
    master_username: str | None = None
    target_db_name: str = DEFAULT_DATABASE_NAME
    instance_class: str | None = None
    poll_seconds: int = 30
    timeout_seconds: int = 90 * 60
    batch_size: int = DEFAULT_BATCH_SIZE


@dataclass(frozen=True)
class FreezeResult:
    patch: str
    instance_id: str
    endpoint: str
    target_database: str
    queue_id: int
    tft_set_number: int
    rows_by_table: dict[str, int]
    analytics_counts: dict[str, int]
    validation: dict[str, Any]
    port: int = 5432
    admin: str = ""


class FreezePublicationError(RuntimeError):
    """A post-provision publication failure whose RDS target is retained."""

    def __init__(self, stage: str, instance_id: str, cause: Exception) -> None:
        self.stage = stage
        self.instance_id = instance_id
        self.cause = cause
        super().__init__(
            f"publication failed during {stage}; retained RDS instance "
            f"{instance_id!r}: {cause}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Publish a patch-named, serving-ready RDS database for the "
            "configured patch/queue/set scope."
        )
    )
    parser.add_argument("patch", help="Patch number to freeze, for example 10.5.")
    parser.add_argument(
        "--source-instance-id",
        default=None,
        help=(
            "Existing RDS instance whose settings are used for the new instance "
            "(default: %(default)s)."
        ),
    )
    parser.add_argument(
        "--source-dsn",
        help="Source PostgreSQL DSN. Defaults to the configured application database.",
    )
    parser.add_argument(
        "--master-user-password",
        default=(
            os.environ.get("RDS_MASTER_USER_PASSWORD")
            or os.environ.get("RDS_PASSWORD")
        ),
        help=(
            "Password for the new instance's master user. Defaults to "
            "RDS_MASTER_USER_PASSWORD or RDS_PASSWORD."
        ),
    )
    parser.add_argument(
        "--master-username",
        help="Master username for the new instance. Defaults to the source instance user.",
    )
    parser.add_argument(
        "--target-db-name",
        default=DEFAULT_DATABASE_NAME,
        help="Database created in the target instance (default: %(default)s).",
    )
    parser.add_argument(
        "--instance-class",
        help="Target DB instance class. Defaults to the source instance class.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="Seconds between RDS availability checks (default: %(default)s).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=90 * 60,
        help="Maximum time to wait for the new instance (default: %(default)s).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Rows inserted per transaction (default: %(default)s).",
    )
    return parser


def normalize_patch(patch: str) -> str:
    """Validate the CLI patch format and return its trimmed value."""
    normalized = patch.strip()
    if not _PATCH_RE.fullmatch(normalized):
        raise ValueError(f"patch must look like '<major>.<minor>', got {patch!r}")
    return normalized


def patch_instance_identifier(patch: str) -> str:
    """Return the deterministic RDS identifier for a patch."""
    return f"chat_tft_patch_{normalize_patch(patch).replace('.', '_')}"


def _instance_details(client: Any, instance_id: str) -> dict[str, Any]:
    instances = client.describe_db_instances(DBInstanceIdentifier=instance_id).get(
        "DBInstances", []
    )
    if len(instances) != 1:
        raise RuntimeError(f"RDS instance {instance_id!r} was not found uniquely.")
    return instances[0]


def _instance_exists(client: Any, instance_id: str) -> bool:
    try:
        instances = client.describe_db_instances(DBInstanceIdentifier=instance_id).get(
            "DBInstances", []
        )
        if not instances:
            return False
        if len(instances) != 1:
            raise RuntimeError(f"RDS instance {instance_id!r} was not found uniquely.")
    except Exception as exc:  # noqa: BLE001
        response = getattr(exc, "response", {}) or {}
        error = response.get("Error", {})
        if error.get("Code") in {"DBInstanceNotFound", "DBInstanceNotFoundFault"}:
            return False
        raise
    return True


def _optional_request_value(request: dict[str, Any], key: str, value: Any) -> None:
    if value is not None:
        request[key] = value


def build_create_request(
    source_instance: dict[str, Any],
    *,
    instance_id: str,
    password: str,
    database_name: str,
    master_username: str | None = None,
    instance_class: str | None = None,
    patch: str | None = None,
) -> dict[str, Any]:
    """Build an RDS ``create_db_instance`` request from source settings."""
    username = master_username or source_instance.get("MasterUsername")
    if not username:
        raise ValueError("the source instance did not report MasterUsername")
    source_class = instance_class or source_instance.get("DBInstanceClass")
    if not source_class:
        raise ValueError("the source instance did not report DBInstanceClass")
    engine = source_instance.get("Engine")
    storage = source_instance.get("AllocatedStorage")
    if not engine or storage is None:
        raise ValueError("the source instance did not report Engine and AllocatedStorage")

    request: dict[str, Any] = {
        "DBInstanceIdentifier": instance_id,
        "DBInstanceClass": source_class,
        "Engine": engine,
        "AllocatedStorage": storage,
        "MasterUsername": username,
        "MasterUserPassword": password,
        "DBName": database_name,
        "CopyTagsToSnapshot": True,
        "Tags": [
            {"Key": "Name", "Value": instance_id},
            *([{"Key": "TFTPatch", "Value": patch}] if patch else []),
        ],
    }
    endpoint = source_instance.get("Endpoint") or {}
    _optional_request_value(request, "Port", endpoint.get("Port"))
    _optional_request_value(request, "EngineVersion", source_instance.get("EngineVersion"))
    _optional_request_value(request, "StorageType", source_instance.get("StorageType"))
    _optional_request_value(request, "StorageEncrypted", source_instance.get("StorageEncrypted"))
    if source_instance.get("StorageEncrypted"):
        _optional_request_value(request, "KmsKeyId", source_instance.get("KmsKeyId"))
    _optional_request_value(request, "MultiAZ", source_instance.get("MultiAZ"))
    _optional_request_value(
        request, "PubliclyAccessible", source_instance.get("PubliclyAccessible")
    )
    _optional_request_value(
        request, "AutoMinorVersionUpgrade", source_instance.get("AutoMinorVersionUpgrade")
    )
    subnet_group = (source_instance.get("DBSubnetGroup") or {}).get("DBSubnetGroupName")
    _optional_request_value(request, "DBSubnetGroupName", subnet_group)
    security_groups = [
        group["VpcSecurityGroupId"]
        for group in source_instance.get("VpcSecurityGroups", [])
        if group.get("VpcSecurityGroupId")
    ]
    if security_groups:
        request["VpcSecurityGroupIds"] = security_groups
    return request


def _wait_for_instance(
    client: Any,
    *,
    instance_id: str,
    poll_seconds: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    # The AWS waiter has the correct RDS state transitions and timeout
    # behavior.  The explicit arguments are retained in the public options so
    # callers can use the same contract with a polling fake in tests.
    waiter = client.get_waiter("db_instance_available")
    waiter.wait(
        DBInstanceIdentifier=instance_id,
        WaiterConfig={
            "Delay": poll_seconds,
            "MaxAttempts": max(1, (timeout_seconds + poll_seconds - 1) // poll_seconds),
        },
    )
    return _instance_details(client, instance_id)


def provision_patch_instance(
    client: Any,
    options: FreezeOptions,
) -> tuple[str, dict[str, Any]]:
    """Create and wait for the patch-named RDS instance."""
    patch = normalize_patch(options.patch)
    if not options.master_user_password:
        raise ValueError(
            "a master password is required; pass --master-user-password or set "
            "RDS_MASTER_USER_PASSWORD/RDS_PASSWORD"
        )
    instance_id = patch_instance_identifier(patch)
    if _instance_exists(client, instance_id):
        raise RuntimeError(
            f"RDS instance {instance_id!r} already exists; refusing to overwrite it"
        )

    source = _instance_details(client, options.source_instance_id)
    request = build_create_request(
        source,
        instance_id=instance_id,
        password=options.master_user_password,
        database_name=options.target_db_name,
        master_username=options.master_username,
        instance_class=options.instance_class,
        patch=patch,
    )
    logger.info("Creating RDS instance %s", instance_id)
    client.create_db_instance(**request)
    try:
        target = _wait_for_instance(
            client,
            instance_id=instance_id,
            poll_seconds=options.poll_seconds,
            timeout_seconds=options.timeout_seconds,
        )
    except Exception as exc:
        raise FreezePublicationError("provision-wait", instance_id, exc) from exc
    return instance_id, target


def _scope_clause(scope: AnalysisScopeIdentity) -> Any:
    return and_(
        RawMatch.patch == scope.patch,
        RawMatch.queue_id == scope.queue_id,
        func.coalesce(RawMatch.tft_set_number, 0) == scope.tft_set_number,
    )


def _rows_for_scope(model: type[Any], scope: AnalysisScopeIdentity):
    """Build the exact-scope select used for raw publication copies.

    Args:
        model: Raw graph or metadata model being copied.
        scope: Patch, queue, and set publication identity.

    Returns:
        A selectable constrained to the publication scope.
    """
    columns = tuple(model.__table__.columns)
    if model is RawMatch:
        return select(*columns).where(_scope_clause(scope))
    if model is ItemMetadata:
        return select(*columns).where(
            ItemMetadata.patch == scope.patch,
            ItemMetadata.tft_set_number == scope.tft_set_number,
        )
    matching_match = exists(
        select(1).where(
            RawMatch.match_id == getattr(model, "match_id"),
            _scope_clause(scope),
        )
    )
    return select(*columns).where(matching_match)


def count_scope_rows(
    source: Session,
    scope: AnalysisScopeIdentity,
) -> dict[str, int]:
    """Count the raw graph and metadata snapshot for one exact scope."""
    return {
        model.__tablename__: int(
            source.scalar(
                select(func.count()).select_from(_rows_for_scope(model, scope).subquery())
            )
            or 0
        )
        for model in _PATCH_TABLES
    }


def preflight_scope(source: Session, patch: str) -> tuple[AnalysisScopeIdentity, dict[str, int]]:
    """Resolve and require a non-empty configured raw scope before provisioning."""
    scope = resolve_configured_scope(source, patch=normalize_patch(patch))
    if scope is None:
        raise ValueError(f"No raw matches are available for patch {patch!r}.")
    counts = count_scope_rows(source, scope)
    if counts[RawMatch.__tablename__] == 0:
        raise ValueError(
            f"No raw matches are available for patch {scope.patch!r}, queue "
            f"{scope.queue_id}, set {scope.tft_set_number}."
        )
    if counts[PlayerBoard.__tablename__] == 0:
        raise ValueError(
            f"No player boards are available for patch {scope.patch!r}, queue "
            f"{scope.queue_id}, set {scope.tft_set_number}."
        )
    return scope, counts


def _copy_model_rows(
    source: Session,
    target: Session,
    model: type[Any],
    *,
    scope: AnalysisScopeIdentity,
    batch_size: int,
) -> int:
    columns = [column.name for column in model.__table__.columns]
    rows = source.execute(_rows_for_scope(model, scope)).mappings().yield_per(batch_size)
    copied = 0
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append({column: row[column] for column in columns})
        if len(batch) >= batch_size:
            target.execute(insert(model), batch)
            target.commit()
            copied += len(batch)
            batch.clear()
    if batch:
        target.execute(insert(model), batch)
        target.commit()
        copied += len(batch)
    return copied


def copy_patch_rows(
    source: Session,
    target: Session,
    patch: str | None = None,
    *,
    scope: AnalysisScopeIdentity | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    """Copy one exact patch/queue/set raw graph into an empty target schema."""
    if scope is None:
        if patch is None:
            raise ValueError("patch or scope is required")
        resolved = resolve_configured_scope(source, patch=normalize_patch(patch))
        if resolved is None:
            raise ValueError(f"No configured scope is available for patch {patch!r}.")
        scope = resolved
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    counts: dict[str, int] = {}
    try:
        for model in _PATCH_TABLES:
            counts[model.__tablename__] = _copy_model_rows(
                source,
                target,
                model,
                scope=scope,
                batch_size=batch_size,
            )
    except Exception:
        target.rollback()
        raise
    return counts


def _target_dsn(
    instance: dict[str, Any], *, username: str, password: str, database: str
) -> str:
    endpoint = instance.get("Endpoint") or {}
    host = endpoint.get("Address")
    port = endpoint.get("Port", 5432)
    if not host:
        raise RuntimeError("the new RDS instance did not report an endpoint")
    return f"postgresql://{quote(username)}:{quote(password, safe='')}@{host}:{port}/{database}"


def _begin_source_snapshot(source: Session) -> None:
    """Begin the consistent read transaction used through count and copy."""
    if source.get_bind().dialect.name == "postgresql":
        source.execute(
            text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )


def freeze_patch_db(
    options: FreezeOptions,
    *,
    rds_client: Any | None = None,
) -> FreezeResult:
    """Publish and validate one configured scope on a new RDS instance."""
    patch = normalize_patch(options.patch)
    if not options.source_instance_id:
        raise ValueError("RDS_INSTANCE_ID or --source-instance-id is required")
    source_target = resolve_database_target("app", options.source_dsn)
    source = open_db(source_target, ensure_schema=False)
    instance_id: str | None = None
    target_instance: dict[str, Any] | None = None
    stage = "preflight"
    try:
        _begin_source_snapshot(source)
        scope, source_counts = preflight_scope(source, patch)

        client = rds_client or build_rds_client()
        stage = "provision"
        instance_id, target_instance = provision_patch_instance(client, options)
        username = options.master_username or target_instance.get("MasterUsername")
        if not username:
            raise FreezePublicationError(
                "target-schema",
                instance_id,
                RuntimeError("the new RDS instance did not report MasterUsername"),
            )
        assert options.master_user_password is not None  # validated by provisioning
        try:
            target_dsn = _target_dsn(
                target_instance,
                username=username,
                password=options.master_user_password,
                database=options.target_db_name,
            )
        except Exception as exc:
            raise FreezePublicationError("target-schema", instance_id, exc) from exc

        target: Session | None = None
        try:
            stage = "target-schema"
            target = open_db(target_dsn, ensure_schema=True)
            logger.info(
                "Copying configured scope patch=%s queue=%s set=%s from %s to %s",
                scope.patch,
                scope.queue_id,
                scope.tft_set_number,
                database_label(source_target),
                instance_id,
            )
            stage = "raw-copy"
            copied_counts = copy_patch_rows(
                source,
                target,
                scope=scope,
                batch_size=options.batch_size,
            )
            if copied_counts != source_counts:
                raise RuntimeError(
                    f"copied raw counts do not match source snapshot: "
                    f"source={source_counts}, copied={copied_counts}"
                )

            stage = "analytics-rebuild"
            analytics_counts = rebuild_query_tables(
                target,
                patch=scope.patch,
                batch_size=options.batch_size,
            )
            stage = "validation"
            validation = validate_patch_publication(
                target,
                source_counts=source_counts,
                patch=scope.patch,
                queue_id=scope.queue_id,
                tft_set_number=scope.tft_set_number,
                analytics_counts=analytics_counts,
            )
        except FreezePublicationError:
            raise
        except Exception as exc:
            raise FreezePublicationError(stage, instance_id, exc) from exc
        finally:
            if target is not None:
                target.close()
    finally:
        source.close()

    assert instance_id is not None and target_instance is not None
    logger.info(
        "Patch publication complete for %s: raw=%s analytics=%s",
        scope,
        copied_counts,
        analytics_counts,
    )
    return FreezeResult(
        patch=scope.patch,
        instance_id=instance_id,
        endpoint=(target_instance.get("Endpoint") or {}).get("Address", ""),
        target_database=options.target_db_name,
        queue_id=scope.queue_id,
        tft_set_number=scope.tft_set_number,
        rows_by_table=copied_counts,
        analytics_counts=analytics_counts,
        validation=validation,
        port=int((target_instance.get("Endpoint") or {}).get("Port", 5432)),
        admin=options.master_username or (target_instance.get("MasterUsername") or ""),
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    args = build_parser().parse_args(argv)
    options = FreezeOptions(
        patch=args.patch,
        source_instance_id=args.source_instance_id or config.rds.instance_id,
        source_dsn=args.source_dsn,
        master_user_password=args.master_user_password,
        master_username=args.master_username or config.rds.admin or None,
        target_db_name=args.target_db_name,
        instance_class=args.instance_class,
        poll_seconds=args.poll_seconds,
        timeout_seconds=args.timeout_seconds,
        batch_size=args.batch_size,
    )
    try:
        result = freeze_patch_db(options)
    except FreezePublicationError as exc:
        logger.error(
            "patch publication failed at stage %s; retained instance %s: %s",
            exc.stage,
            exc.instance_id,
            exc.cause,
        )
        return 1
    except Exception as exc:  # noqa: BLE001
        logger.error("patch publication failed before target retention: %s", exc)
        return 1
    print(
        f"Published serving-ready {result.instance_id} "
        f"({result.endpoint}/{result.target_database}) for patch {result.patch}, "
        f"queue {result.queue_id}, set {result.tft_set_number}; "
        f"raw={result.rows_by_table}; analytics={result.analytics_counts}. "
        "Set these app variables for cutover without editing the operator INI:\n"
        f"RDS_INSTANCE_ID={result.instance_id}\n"
        f"RDS_HOST={result.endpoint}\n"
        f"RDS_PORT={result.port}\n"
        f"RDS_ADMIN={result.admin}\n"
        f"RDS_DB={result.target_database}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
