#!/usr/bin/env python3
"""Install analysis covering indexes without blocking table writes.

These indexes intentionally are not declared on ORM metadata: request-time
schema maintenance must never attempt regular CREATE INDEX against populated
production tables. Run this explicit migration before restarting the API.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from db.session import database_label, engine_for, resolve_database_target


logger = logging.getLogger("tft-add-analysis-indexes")


@dataclass(frozen=True)
class AnalysisIndex:
    name: str
    table: str
    columns: tuple[str, ...]

    @property
    def create_sql(self) -> str:
        columns = ", ".join(self.columns)
        return (
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {self.name} "
            f"ON public.{self.table} ({columns})"
        )


ANALYSIS_INDEXES = (
    AnalysisIndex(
        "ix_player_units_unit_match_puuid",
        "player_units",
        ("unit_name", "match_id", "puuid"),
    ),
    AnalysisIndex(
        "ix_player_items_item_match_puuid",
        "player_items",
        ("item_name", "match_id", "puuid"),
    ),
    AnalysisIndex(
        "ix_player_items_item_unit",
        "player_items",
        ("item_name", "unit_name"),
    ),
    AnalysisIndex(
        "ix_player_items_unit_item",
        "player_items",
        ("unit_name", "item_name"),
    ),
)


def _normalized_definition(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace('"', "").strip().lower())


def _definition_matches(index: AnalysisIndex, definition: str) -> bool:
    normalized = _normalized_definition(definition)
    columns = ", ".join(index.columns)
    return (
        f" on public.{index.table} using btree ({columns})" in normalized
        or f" on public.{index.table} ({columns})" in normalized
    )


def _existing_definition(connection: Any, index_name: str) -> str | None:
    return connection.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE schemaname = 'public' AND indexname = :index_name"
        ),
        {"index_name": index_name},
    ).scalar_one_or_none()


def install_analysis_indexes(engine: Any) -> dict[str, list[str]]:
    """Create missing indexes concurrently and verify every exact definition."""
    if engine.dialect.name != "postgresql":
        raise ValueError("Concurrent analysis-index migration requires PostgreSQL.")

    created: list[str] = []
    verified: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for index in ANALYSIS_INDEXES:
            definition = _existing_definition(connection, index.name)
            if definition is not None and not _definition_matches(index, definition):
                raise RuntimeError(
                    f"Index {index.name!r} exists with a different definition; "
                    "rename or drop it explicitly before retrying."
                )
            if definition is None:
                connection.exec_driver_sql(index.create_sql)
                created.append(index.name)
            definition = _existing_definition(connection, index.name)
            if definition is None or not _definition_matches(index, definition):
                raise RuntimeError(f"Index {index.name!r} was not installed as expected.")
            verified.append(index.name)
    return {"created": created, "verified": verified}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install and verify PostgreSQL analysis indexes concurrently."
    )
    parser.add_argument(
        "--dsn",
        help="Explicit maintenance DSN override. Defaults to the configured app RDS target.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    from core.config import load_config

    load_config()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    target = resolve_database_target(args.dsn)
    result = install_analysis_indexes(engine_for(target))
    print(json.dumps({"database": database_label(target), **result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
