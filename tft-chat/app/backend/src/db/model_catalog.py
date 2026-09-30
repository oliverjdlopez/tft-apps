"""Model catalogue for the relational raw store and scoped analytics.

This backend has no Pydantic model layer -- it stores boards directly through
SQLAlchemy ORM classes. This module builds the same catalogue shape the data
explorer's *Models* tab renders (``{"total", "groups"}``) straight from those
ORM tables.
"""

from __future__ import annotations

import inspect
from typing import Any

from sqlalchemy import Column
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from .models import (
    AnalysisProcessedMatch,
    AnalysisScope,
    BoardTrait,
    BoardUnit,
    ItemMetadata,
    ItemStatQueryTable,
    Match,
    PlayerBoard,
    RawMatch,
    TraitStatQueryTable,
    UnitItem,
    UnitLoadoutStatQueryTable,
    UnitStatQueryTable,
)

# Grouped the way the schema documents itself: the raw board-per-player tables
# first, then the derived query tables.
MODEL_CATEGORIES: list[tuple[str, str, str, list[Any]]] = [
    (
        "match_store",
        "Match store",
        "Normalized match, participant-board, exact unit-copy/item-slot, "
        "item-metadata, and trait-state hierarchy.",
        [RawMatch, PlayerBoard, BoardUnit, UnitItem, BoardTrait, ItemMetadata],
    ),
    (
        "query_tables",
        "Query tables",
        "Analysis scopes, the idempotency ledger, compatibility projection, and "
        "four pre-aggregated tables used by analysis tools.",
        [
            AnalysisScope,
            AnalysisProcessedMatch,
            Match,
            UnitStatQueryTable,
            ItemStatQueryTable,
            TraitStatQueryTable,
            UnitLoadoutStatQueryTable,
        ],
    ),
]

# SQLAlchemy generic types render as their SQL spelling (e.g. VARCHAR); map the
# common ones to a JSON-schema type for the per-model schema block.
_JSON_TYPES: dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "biginteger": "integer",
    "float": "number",
    "boolean": "boolean",
}


def _json_type(column: Column[Any]) -> str:
    name = type(column.type).__name__.lower()
    return _JSON_TYPES.get(name, "string")


def _table_ddl(model: type[Any]) -> str:
    return str(
        CreateTable(model.__table__).compile(dialect=postgresql.dialect())
    ).strip()


def _describe_model(model: type[Any], category: str) -> dict[str, Any]:
    columns = list(model.__table__.columns)
    pk = {column.name for column in model.__table__.primary_key.columns}
    fields = [
        {
            "name": column.name,
            "attr": column.name,
            "type": str(column.type),
            "required": not column.nullable,
            "default": None,
            "description": column.comment,
        }
        for column in columns
    ]
    json_schema = {
        "title": model.__name__,
        "type": "object",
        "properties": {
            column.name: {"type": _json_type(column)} for column in columns
        },
        "required": [column.name for column in columns if not column.nullable],
    }
    return {
        "name": model.__name__,
        "category": category,
        "doc": inspect.getdoc(model) or "",
        "fields": fields,
        "json_schema": json_schema,
        "config": {"primary_key": sorted(pk)},
        "table": model.__tablename__,
        "table_columns": [column.name for column in columns],
        "table_ddl": _table_ddl(model),
    }


def describe_models() -> dict[str, Any]:
    """Describe the dev_db ORM tables as the explorer's Models catalogue."""
    groups: list[dict[str, Any]] = []
    for key, label, blurb, models in MODEL_CATEGORIES:
        groups.append(
            {
                "key": key,
                "label": label,
                "blurb": blurb,
                "models": [_describe_model(model, key) for model in models],
            }
        )
    total = sum(len(group["models"]) for group in groups)
    return {"total": total, "groups": groups}


__all__ = ["describe_models"]
