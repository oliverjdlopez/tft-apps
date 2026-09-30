"""CLI to run table-update functions from ``scripts/update_tables/fn.py``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Callable


# Add the backend src to path to import config loader
sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "app" / "backend" / "src")
)
from core.config import load_config

from db.models import TABLE_MODELS
from db.session import database_label, open_db

from . import fn as fn_module

DEFAULT_BATCH_SIZE = 2000

logger = logging.getLogger("tft-update-tables")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a table-update function from scripts/update_tables/fn.py "
            "against one or more tables."
        )
    )
    parser.add_argument(
        "tables",
        nargs="+",
        help=f"Table name(s) to update. Choices: {', '.join(sorted(TABLE_MODELS))}",
    )
    parser.add_argument(
        "--function",
        default="dientity",
        help=(
            "Name of the function in scripts/update_tables/fn.py to apply to each "
            "table. Defaults to 'dientity', a no-op table function."
        ),
    )
    parser.add_argument(
        "--dsn",
        help="Explicit maintenance DSN override. Defaults to the configured app RDS target.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            "Rows to read/commit per batch (keyset-paginated by primary key). "
            f"Defaults to {DEFAULT_BATCH_SIZE}."
        ),
    )

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _resolve_function(name: str) -> Callable[..., int]:
    fn = getattr(fn_module, name, None)
    if fn is None or not callable(fn):
        raise ValueError(f"fn.py has no function named {name!r}")
    return fn


def update_table(
    session: Any,
    table: str,
    update_fn: Callable[..., int],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Run *update_fn* for one table and return its affected-row count."""
    if table not in TABLE_MODELS:
        raise ValueError(
            f"Unknown table {table!r}. Choices: {', '.join(sorted(TABLE_MODELS))}"
        )
    return update_fn(session, table, batch_size=batch_size)


def update_tables(args: argparse.Namespace) -> dict[str, Any]:
    update_fn = _resolve_function(args.function)

    session = open_db(args.dsn)
    try:
        counts: dict[str, int] = {}
        for table in args.tables:
            counts[table] = update_table(session, table, update_fn, args.batch_size)
            logger.info("Updated %s rows in %s", counts[table], table)
        return {
            "database": database_label(args.dsn),
            "function": args.function,
            "tables": counts,
        }
    finally:
        session.close()


def main(argv: list[str] | None = None) -> None:
    load_config()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    for noisy in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.orm"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    result = update_tables(parse_args(argv))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
