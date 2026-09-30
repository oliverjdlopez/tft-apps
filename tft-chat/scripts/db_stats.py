#!/usr/bin/env python3
"""Report row counts for the latest patch in the application database."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Make the script runnable directly from a checkout as well as through its
# installed console command.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app" / "backend" / "src"))

from sqlalchemy import func  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from core.config import resolve_database_target  # noqa: E402
from db.models import (  # noqa: E402
    AnalysisProcessedMatch,
    AnalysisScope,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    ItemStatQueryTable,
    PlayerBoard,
    RawMatch,
    TraitStatQueryTable,
    UnitItem,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
)
from db.session import database_label, open_db  # noqa: E402


_PATCH_RE = re.compile(r"^\d+(?:\.\d+)+$")
_QUERY_TABLES = (
    ("unit_stats", UnitStatQueryTable),
    ("item_stats", ItemStatQueryTable),
    ("trait_stats", TraitStatQueryTable),
    ("unit_loadout_stats", UnitLoadoutStatQueryTable),
)


def _patch_key(patch: str) -> tuple[int, ...] | None:
    match = _PATCH_RE.fullmatch(patch.strip())
    return tuple(int(part) for part in patch.strip().split(".")) if match else None


def latest_patch(session: Session) -> str | None:
    """Return the highest numeric patch stored in ``raw_matches``."""
    patches = (
        session.query(RawMatch.patch)
        .filter(RawMatch.patch.is_not(None))
        .distinct()
        .all()
    )
    valid_patches = [patch for (patch,) in patches if _patch_key(patch) is not None]
    return (
        max(valid_patches, key=lambda patch: _patch_key(patch) or ())
        if valid_patches
        else None
    )


def _count(session: Session, model: Any, patch: str) -> int:
    return int(
        session.query(func.count())
        .select_from(model)
        .join(RawMatch, model.match_id == RawMatch.match_id)
        .filter(RawMatch.patch == patch)
        .scalar()
        or 0
    )


def collect_stats(session: Session) -> dict[str, Any]:
    """Collect raw and derived row counts for the latest stored patch."""
    patch = latest_patch(session)
    if patch is None:
        return {
            "latest_patch": None,
            "matches": 0,
            "participants": 0,
            "units": 0,
            "items": 0,
            "item_metadata": 0,
            "traits": 0,
            "latest_match_at": None,
            "analysis": {
                "scopes": [],
                "processed_matches": 0,
                "query_rows": {name: 0 for name, _model in _QUERY_TABLES},
            },
        }

    matches = int(
        session.query(func.count(RawMatch.match_id))
        .filter(RawMatch.patch == patch)
        .scalar()
        or 0
    )
    participants = _count(session, PlayerBoard, patch)
    units = _count(session, BoardUnit, patch)
    items = _count(session, UnitItem, patch)
    item_metadata = int(
        session.query(func.count())
        .select_from(ItemMetadata)
        .filter(ItemMetadata.patch == patch)
        .scalar()
        or 0
    )
    traits = _count(session, BoardTrait, patch)

    scopes = (
        session.query(AnalysisScope)
        .filter(AnalysisScope.patch == patch)
        .order_by(AnalysisScope.queue_id, AnalysisScope.tft_set_number)
        .all()
    )
    scope_ids = [scope.scope_id for scope in scopes]
    processed_by_scope: dict[int, int] = {}
    if scope_ids:
        processed_by_scope = {
            scope_id: int(count)
            for scope_id, count in session.query(
                AnalysisProcessedMatch.scope_id,
                func.count().label("matches"),
            )
            .filter(AnalysisProcessedMatch.scope_id.in_(scope_ids))
            .group_by(AnalysisProcessedMatch.scope_id)
            .all()
        }
    query_rows = {
        name: (
            int(
                session.query(func.count())
                .select_from(model)
                .filter(model.scope_id.in_(scope_ids))
                .scalar()
                or 0
            )
            if scope_ids
            else 0
        )
        for name, model in _QUERY_TABLES
    }

    return {
        "latest_patch": patch,
        "matches": matches,
        "participants": participants,
        "units": units,
        "items": items,
        "item_metadata": item_metadata,
        "traits": traits,
        "latest_match_at": session.query(func.max(RawMatch.game_datetime))
        .filter(RawMatch.patch == patch)
        .scalar(),
        "analysis": {
            "scopes": [
                {
                    "scope_id": scope.scope_id,
                    "queue_id": scope.queue_id,
                    "tft_set_number": scope.tft_set_number,
                    "status": scope.status,
                    "is_active": scope.is_active,
                    "universe_boards": scope.universe_boards,
                    "processed_matches": processed_by_scope.get(scope.scope_id, 0),
                }
                for scope in scopes
            ],
            "processed_matches": sum(processed_by_scope.values()),
            "query_rows": query_rows,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report current database row counts for the latest stored TFT patch."
    )
    parser.add_argument(
        "--dsn",
        help="Explicit PostgreSQL DSN. Defaults to the configured application database.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target = resolve_database_target("app", args.dsn)
    session = open_db(target, ensure_schema=False)
    try:
        result = {"database": database_label(target), **collect_stats(session)}
    finally:
        session.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
