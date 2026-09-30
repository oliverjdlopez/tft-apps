"""One-off repair for persisted unit costs and their analytics projections.

The command audits the configured patch/queue/set scope against exact-patch
Community Dragon champion metadata. Dry-run is the default. ``--apply`` updates
only mismatched ``board_units.cost`` values, marks existing analytics dirty,
commits the raw repair, and performs a full scope rebuild.
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from db.build_query_tables import (
    AnalysisScopeIdentity,
    rebuild_query_tables,
    resolve_configured_scope,
)
from db.insert import get_patch_resolver
from db.models import (
    AnalysisFactBuild,
    AnalysisScope,
    BoardUnit,
    RawMatch,
)
from db.models.base import utc_now
from db.session import database_label, engine_for, resolve_database_target
from utils.tft import TFTNameResolver

logger = logging.getLogger("tft-repair-unit-costs")

ResolverFactory = Callable[[str, int | None], TFTNameResolver]
RebuildFunction = Callable[..., dict[str, int]]


def scope_match_ids(identity: AnalysisScopeIdentity) -> Any:
    """Build the raw-match selector for one analysis scope.

    Args:
        identity: Configured patch, queue, and TFT-set identity.

    Returns:
        A scalar-select statement containing matching raw match IDs.
    """
    return select(RawMatch.match_id).where(
        RawMatch.patch == identity.patch,
        RawMatch.queue_id == identity.queue_id,
        func.coalesce(RawMatch.tft_set_number, 0) == identity.tft_set_number,
    )


def audit_unit_costs(
    session: Session,
    *,
    identity: AnalysisScopeIdentity,
    resolver: TFTNameResolver,
) -> dict[str, Any]:
    """Compare persisted cost distributions with exact-patch static costs.

    Args:
        session: Read-capable maintenance session.
        identity: Scope whose raw unit rows are audited.
        resolver: Exact-patch Community Dragon resolver for the scope's set.

    Returns:
        JSON-serializable scan counts, mismatches, and unresolved unit names.
    """
    rows = session.execute(
        select(
            BoardUnit.unit_name,
            BoardUnit.cost,
            func.count().label("rows"),
        )
        .where(BoardUnit.match_id.in_(scope_match_ids(identity)))
        .group_by(BoardUnit.unit_name, BoardUnit.cost)
        .order_by(BoardUnit.unit_name, BoardUnit.cost)
    ).all()

    stored_by_unit: dict[str, list[dict[str, int | None]]] = {}
    scanned_rows = 0
    for row in rows:
        count = int(row.rows)
        scanned_rows += count
        stored_by_unit.setdefault(str(row.unit_name), []).append(
            {"cost": None if row.cost is None else int(row.cost), "rows": count}
        )

    mismatches: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    mismatched_rows = 0
    for unit_name, stored_costs in stored_by_unit.items():
        static_cost = resolver.unit_cost(unit_name)
        if static_cost is None:
            unresolved.append(
                {"unit_name": unit_name, "stored_costs": stored_costs}
            )
            continue
        differing_rows = sum(
            int(entry["rows"] or 0)
            for entry in stored_costs
            if entry["cost"] != int(static_cost)
        )
        if differing_rows:
            mismatched_rows += differing_rows
            mismatches.append(
                {
                    "unit_name": unit_name,
                    "static_cost": int(static_cost),
                    "stored_costs": stored_costs,
                    "mismatched_rows": differing_rows,
                }
            )

    return {
        "scanned_units": len(stored_by_unit),
        "scanned_rows": scanned_rows,
        "mismatched_units": len(mismatches),
        "mismatched_rows": mismatched_rows,
        "unresolved_units": len(unresolved),
        "mismatches": mismatches,
        "unresolved": unresolved,
    }


def mark_scope_dirty(
    session: Session,
    *,
    identity: AnalysisScopeIdentity,
) -> bool:
    """Mark an existing scope and fact build dirty before committing repairs.

    Args:
        session: Maintenance transaction containing raw unit updates.
        identity: Scope affected by those updates.

    Returns:
        Whether an existing analysis scope was marked dirty.
    """
    scope = session.scalar(
        select(AnalysisScope).where(
            AnalysisScope.patch == identity.patch,
            AnalysisScope.queue_id == identity.queue_id,
            AnalysisScope.tft_set_number == identity.tft_set_number,
        )
    )
    if scope is None:
        return False

    marked_at = utc_now()
    reason = "unit costs repaired from exact-patch Community Dragon metadata"
    scope.status = "dirty"
    scope.last_error_at = marked_at
    scope.last_error_details = reason
    fact_build = session.get(AnalysisFactBuild, scope.scope_id)
    if fact_build is not None:
        fact_build.status = "dirty"
        fact_build.updated_at = marked_at
        fact_build.last_error_at = marked_at
        fact_build.last_error_details = reason
    return True


def apply_unit_cost_repairs(
    session: Session,
    *,
    identity: AnalysisScopeIdentity,
    mismatches: list[dict[str, Any]],
) -> int:
    """Apply an audited static cost to each mismatched raw unit identity.

    Args:
        session: Maintenance transaction to update.
        identity: Scope restricting every update.
        mismatches: Audit entries containing unit names and static costs.

    Returns:
        Number of raw ``board_units`` rows updated.
    """
    repaired_rows = 0
    match_ids = scope_match_ids(identity)
    for mismatch in mismatches:
        static_cost = int(mismatch["static_cost"])
        result = session.execute(
            update(BoardUnit)
            .where(
                BoardUnit.match_id.in_(match_ids),
                BoardUnit.unit_name == str(mismatch["unit_name"]),
                BoardUnit.cost.is_distinct_from(static_cost),
            )
            .values(cost=static_cost)
        )
        repaired_rows += int(result.rowcount or 0)
    return repaired_rows


def repair_unit_costs(
    session: Session,
    *,
    apply: bool,
    patch: str | None = None,
    batch_size: int = 500,
    resolver_factory: ResolverFactory = get_patch_resolver,
    rebuild_function: RebuildFunction = rebuild_query_tables,
) -> dict[str, Any]:
    """Audit or repair one scope and rebuild its model-facing projections.

    Args:
        session: Maintenance session for the target database.
        apply: Whether to persist repairs and run the full rebuild.
        patch: Optional configured-scope patch override.
        batch_size: Match page size used by the full rebuild.
        resolver_factory: Injectable exact-patch resolver factory.
        rebuild_function: Injectable full-rebuild operation.

    Returns:
        Scope identity, before/after audits, repair count, and rebuild result.

    Raises:
        RuntimeError: If the requested/configured scope has no represented data.
        ValueError: If ``batch_size`` is not positive.
    """
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    identity = resolve_configured_scope(session, patch=patch)
    if identity is None:
        raise RuntimeError("No represented analysis scope is available to repair.")

    resolver = resolver_factory(identity.patch, identity.tft_set_number)
    before = audit_unit_costs(session, identity=identity, resolver=resolver)
    result: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "scope": {
            "patch": identity.patch,
            "queue_id": identity.queue_id,
            "tft_set_number": identity.tft_set_number,
        },
        "before": before,
        "repaired_rows": 0,
        "scope_marked_dirty": False,
        "rebuild": None,
        "after": None,
    }
    if not apply:
        session.rollback()
        return result

    repaired_rows = apply_unit_cost_repairs(
        session,
        identity=identity,
        mismatches=before["mismatches"],
    )
    marked_dirty = (
        mark_scope_dirty(session, identity=identity) if repaired_rows else False
    )
    session.commit()
    logger.info(
        "Committed raw unit-cost repair scope=%s repaired_rows=%d marked_dirty=%s",
        result["scope"],
        repaired_rows,
        marked_dirty,
    )

    rebuild = rebuild_function(
        session,
        patch=identity.patch,
        batch_size=batch_size,
    )
    after = audit_unit_costs(session, identity=identity, resolver=resolver)
    if after["mismatched_rows"]:
        raise RuntimeError(
            "Unit-cost repair verification failed: "
            f"{after['mismatched_rows']} resolved rows still mismatch static metadata."
        )
    result.update(
        {
            "repaired_rows": repaired_rows,
            "scope_marked_dirty": marked_dirty,
            "rebuild": rebuild,
            "after": after,
        }
    )
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build the one-off maintenance command parser.

    Returns:
        Parser whose default mode is a non-mutating audit.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dsn",
        help="Explicit PostgreSQL maintenance DSN; defaults to the app target.",
    )
    parser.add_argument(
        "--patch",
        help="Patch override for configured-scope selection, for example 16.10.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Match page size used by the full rebuild (default: %(default)s).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist cost repairs and fully rebuild the selected scope.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Run the audit or authorized repair against one maintenance target.

    Args:
        argv: Optional command-line arguments for tests and direct invocation.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    args = build_parser().parse_args(argv)
    target = resolve_database_target("app", args.dsn)
    label = database_label(target)
    logger.info("Database: %s", label)
    with sessionmaker(bind=engine_for(target), expire_on_commit=False)() as session:
        result = repair_unit_costs(
            session,
            apply=args.apply,
            patch=args.patch,
            batch_size=args.batch_size,
        )
    print(json.dumps({"database": label, **result}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
