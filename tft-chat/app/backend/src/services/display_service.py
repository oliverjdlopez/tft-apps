"""Data explorer service.

This module owns the explorer implementation for model/schema introspection,
database browsing, native tool catalogue/calls, and raw upstream API previews.
HTTP routes should delegate here.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
from sqlalchemy import String, cast, inspect as sa_inspect, or_

from common.serialization import strict_jsonable, to_jsonable, truncate_json
from core.cdragon import CDRAGON_TFT_DATA_URL
from core.config import load_config
from core.routing import (
    PLATFORM_TO_REGION,
    PLATFORMS,
    REGIONS,
    platform_host,
    region_host,
)
from db.model_catalog import describe_models as describe_db_models
from db.models import TABLE_MODELS
from db.session import TABLE_SCHEMA, database_label, open_db
from domain.tools import (
    call_tool,
    get_tool_group_key,
    list_tool_group_metadata,
    list_tool_metadata,
)
from domain.tools.schemas import invocation_schema

# Cap the size of raw responses we forward to the browser. Static-data payloads
# run to hundreds of KB; the point of the raw view is to see the shape, not to
# move megabytes into the page.
RAW_PREVIEW_BYTES = 200_000
logger = logging.getLogger(__name__)


def _model_to_dict(row: Any) -> dict[str, Any]:
    """Return a plain dict for one mapped ORM row from any mapped table."""

    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


# ---------------------------------------------------------------------------
# Live database introspection
# ---------------------------------------------------------------------------


def describe_db(sample_rows: int = 0) -> dict[str, Any]:
    """Introspect tables, columns, row counts, and optional samples."""
    table_models = TABLE_MODELS
    session = open_db()
    try:
        inspector = sa_inspect(session.get_bind())
        tables = [
            table for table in inspector.get_table_names(schema=TABLE_SCHEMA)
            if table in table_models
        ]
        out_tables = []
        for t in tables:
            cols = [
                {
                    "name": column["name"],
                    "type": str(column["type"]),
                    "nullable": bool(column.get("nullable")),
                }
                for column in inspector.get_columns(t, schema=TABLE_SCHEMA)
            ]
            model = table_models[t]
            count = session.query(model).count()
            entry: dict[str, Any] = {
                "name": t,
                "columns": cols,
                "rows": int(count),
                "model": model.__name__,
            }
            if sample_rows and count:
                rs = session.query(model).limit(int(sample_rows)).all()
                entry["sample"] = [_model_to_dict(row) for row in rs]
            out_tables.append(entry)
        return {"db_path": database_label(), "tables": out_tables}
    finally:
        session.close()


def _table_columns(session: Any, table: str) -> list[dict[str, Any]]:
    inspector = sa_inspect(session.get_bind())
    return [
        {
            "name": column["name"],
            "type": str(column["type"]),
            "nullable": bool(column.get("nullable")),
        }
        for column in inspector.get_columns(table, schema=TABLE_SCHEMA)
    ]


def browse_table(
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
    direction: str = "asc",
    q: str = "",
) -> dict[str, Any]:
    """Return one read-only page of rows from a live database table."""
    limit = max(1, min(int(limit), 200))
    offset = max(0, int(offset))
    direction = "desc" if direction.lower() == "desc" else "asc"
    q = q.strip()

    table_models = TABLE_MODELS
    session = open_db()
    try:
        if table not in table_models:
            raise KeyError(table)
        model = table_models[table]

        columns = _table_columns(session, table)
        column_names = [c["name"] for c in columns]
        if sort not in column_names:
            sort = column_names[0] if column_names else None

        query = session.query(model)
        total = query.count()
        if q and column_names:
            needle = f"%{q}%"
            query = query.filter(
                or_(*(cast(getattr(model, column), String).ilike(needle) for column in column_names))
            )
        filtered = query.count()

        if sort:
            sort_attr = getattr(model, sort)
            query = query.order_by(sort_attr.desc() if direction == "desc" else sort_attr.asc())
        rows = query.limit(limit).offset(offset).all()

        return {
            "db_path": database_label(),
            "table": table,
            "columns": columns,
            "rows": [_model_to_dict(row) for row in rows],
            "total_rows": int(total),
            "filtered_rows": int(filtered),
            "limit": limit,
            "offset": offset,
            "sort": sort,
            "direction": direction,
            "q": q,
        }
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Raw HTTP API catalogue
#
# This mirrors exactly what the backend clients do, so the UI can
# fire the underlying request and show the unprocessed JSON. Param specs let
# the frontend build a form. Execution lives in display_service.raw_call.
# ---------------------------------------------------------------------------

RAW_CATALOG: list[dict[str, Any]] = [
    {
        "id": "cdragon_tft_data",
        "source": "Community Dragon",
        "label": "TFT static data payload",
        "method": "GET",
        "url_template": CDRAGON_TFT_DATA_URL,
        "needs_key": False,
        "host_kind": None,
        "params": [
            {"name": "patch", "default": "latest", "required": True},
            {"name": "locale", "default": "default", "required": True},
        ],
        "notes": (
            "Single Community Dragon TFT payload with items and setData, "
            "including champion traits, abilities, stats, trait thresholds, "
            "and item composition/effects. The client validates this for "
            "ingestion and stored-name resolution."
        ),
    },
    {
        "id": "riot_account_by_riot_id",
        "source": "Riot API",
        "label": "Account-V1: Riot ID -> PUUID",
        "method": "GET",
        "url_template": "https://{host}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}",
        "needs_key": True,
        "host_kind": "regional",
        "params": [
            {"name": "game_name", "default": "", "required": True},
            {"name": "tag_line", "default": "", "required": True},
            {"name": "region", "default": "americas", "required": True, "enum": sorted(REGIONS)},
        ],
        "notes": "Regional routing. Resolves a Riot ID to the PUUID everything else keys on.",
    },
    {
        "id": "riot_summoner_by_puuid",
        "source": "Riot API",
        "label": "TFT-Summoner-V1: profile by PUUID",
        "method": "GET",
        "url_template": "https://{host}/tft/summoner/v1/summoners/by-puuid/{puuid}",
        "needs_key": True,
        "host_kind": "platform",
        "params": [
            {"name": "puuid", "default": "", "required": True},
            {"name": "platform", "default": "na1", "required": True, "enum": sorted(PLATFORMS)},
        ],
        "notes": "Platform routing.",
    },
    {
        "id": "riot_match_ids",
        "source": "Riot API",
        "label": "TFT-Match-V1: recent match ids",
        "method": "GET",
        "url_template": "https://{host}/tft/match/v1/matches/by-puuid/{puuid}/ids",
        "needs_key": True,
        "host_kind": "regional",
        "params": [
            {"name": "puuid", "default": "", "required": True},
            {"name": "region", "default": "americas", "required": True, "enum": sorted(REGIONS)},
            {"name": "count", "default": "5", "required": False, "query": True},
            {"name": "start", "default": "0", "required": False, "query": True},
        ],
        "notes": "Regional routing. count/start are query params.",
    },
    {
        "id": "riot_match",
        "source": "Riot API",
        "label": "TFT-Match-V1: full match",
        "method": "GET",
        "url_template": "https://{host}/tft/match/v1/matches/{match_id}",
        "needs_key": True,
        "host_kind": "regional",
        "params": [
            {"name": "match_id", "default": "", "required": True},
            {"name": "region", "default": "americas", "required": True, "enum": sorted(REGIONS)},
        ],
        "notes": "The payload RiotMatch validates for match data.",
    },
    {
        "id": "riot_league_entries",
        "source": "Riot API",
        "label": "TFT-League-V1: ranked entries",
        "method": "GET",
        "url_template": "https://{host}/tft/league/v1/by-puuid/{puuid}",
        "needs_key": True,
        "host_kind": "platform",
        "params": [
            {"name": "puuid", "default": "", "required": True},
            {"name": "platform", "default": "na1", "required": True, "enum": sorted(PLATFORMS)},
        ],
        "notes": "Platform routing.",
    },
    {
        "id": "riot_top_league",
        "source": "Riot API",
        "label": "TFT-League-V1: top ladder",
        "method": "GET",
        "url_template": "https://{host}/tft/league/v1/{tier}",
        "needs_key": True,
        "host_kind": "platform",
        "params": [
            {
                "name": "tier",
                "default": "challenger",
                "required": True,
                "enum": ["challenger", "grandmaster", "master"],
            },
            {"name": "platform", "default": "na1", "required": True, "enum": sorted(PLATFORMS)},
            {"name": "queue", "default": "RANKED_TFT", "required": False, "query": True},
        ],
        "notes": "Platform routing.",
    },
    {
        "id": "riot_platform_status",
        "source": "Riot API",
        "label": "TFT-Status-V1: shard status",
        "method": "GET",
        "url_template": "https://{host}/tft/status/v1/platform-data",
        "needs_key": True,
        "host_kind": "platform",
        "params": [
            {"name": "platform", "default": "na1", "required": True, "enum": sorted(PLATFORMS)},
        ],
        "notes": "Platform routing. No key-sensitive params; good first live test.",
    },
]

RAW_BY_ID = {e["id"]: e for e in RAW_CATALOG}

ROUTING_INFO = {
    "platforms": sorted(PLATFORMS),
    "regions": sorted(REGIONS),
    "platform_to_region": PLATFORM_TO_REGION,
}



def overview() -> dict[str, Any]:
    tools = list_tool_metadata()
    by_cat: dict[str, int] = {}
    for tool in tools:
        cat = get_tool_group_key(tool["name"])
        by_cat[cat] = by_cat.get(cat, 0) + 1
    db_info = describe_db()
    rows_by_table = {
        table["name"]: int(table["rows"]) for table in db_info["tables"]
    }
    models_info = describe_db_models()
    return {
        "tools": {"total": len(tools), "by_category": by_cat},
        "models": {"total": models_info["total"]},
        "db": {
            "path": db_info["db_path"],
            "tables": len(db_info["tables"]),
            "scoped_boards": rows_by_table.get("matches", 0),
            "raw_boards": rows_by_table.get("all_matches", 0),
        },
        "api_key_configured": bool(load_config().secrets.riot_api_key),
        "sources": [
            {
                "name": "Community Dragon",
                "needs_key": False,
                "blurb": "Static catalogue and set metadata: champions, traits, items.",
            },
            {
                "name": "Riot API",
                "needs_key": True,
                "blurb": "Live player / match / league data; feeds the database.",
            },
        ],
    }


def models() -> dict[str, Any]:
    return describe_db_models()


def db(sample: int = 0) -> dict[str, Any]:
    return describe_db(sample_rows=sample)


def db_table_rows(
    table: str,
    *,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
    direction: str = "asc",
    q: str = "",
) -> dict[str, Any]:
    try:
        return strict_jsonable(
            browse_table(
                table,
                limit=limit,
                offset=offset,
                sort=sort,
                direction=direction,
                q=q,
            )
        )
    except KeyError:
        raise LookupError(f"Unknown table: {table}") from None


def tool_catalog() -> dict[str, Any]:
    """Return model-facing and locally invocable tool schemas for Explorer.

    Returns:
        Registered tool metadata grouped for display. Each tool retains its
        strict OpenAI input schema and adds the schema used to build a local
        invocation form with accurate required-field semantics.
    """

    tools = [
        {
            **tool,
            "invocation_schema": invocation_schema(tool["input_schema"]),
        }
        for tool in list_tool_metadata()
    ]
    tools_by_name = {tool["name"]: tool for tool in tools}
    groups = [
        {
            **group,
            "tools": [tools_by_name[tool["name"]] for tool in group["tools"]],
        }
        for group in list_tool_group_metadata()
    ]
    return {
        "total": len(tools),
        "tools": tools,
        "groups": groups,
    }


async def tool_call(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Invoke a native OpenAI SDK tool and return its JSON-compatible output."""
    call_arguments = arguments or {}
    t0 = time.perf_counter()
    try:
        structured = await call_tool(name, call_arguments)
    except Exception as e:  # noqa: BLE001 - surface every failure to the UI
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }

    return {
        "ok": True,
        "name": name,
        "arguments": call_arguments,
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        "content_blocks": [],
        "structured": to_jsonable(structured),
    }


def raw_catalog() -> dict[str, Any]:
    return {"endpoints": RAW_CATALOG, "routing": ROUTING_INFO}


def _build_raw_request(entry: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Construct the exact URL / query / headers for a raw upstream call."""
    p = {k: (v if v is not None else "") for k, v in params.items()}
    query: dict[str, Any] = {}
    headers: dict[str, str] = {}

    host = None
    if entry["host_kind"] == "platform":
        host = platform_host(p["platform"])
    elif entry["host_kind"] == "regional":
        host = region_host(p["region"])

    for spec in entry["params"]:
        if spec.get("query") and p.get(spec["name"]) not in (None, ""):
            query[spec["name"]] = p[spec["name"]]

    url = entry["url_template"]
    fmt: dict[str, Any] = dict(p)
    if host:
        fmt["host"] = host
    url = url.format(**fmt)

    if entry["needs_key"]:
        key = load_config().secrets.riot_api_key
        if not key:
            raise RuntimeError("RIOT_API_KEY is not set; this endpoint needs a Riot key.")
        headers["X-Riot-Token"] = key

    return {"url": url, "query": query, "headers": headers}


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out = dict(headers)
    if "X-Riot-Token" in out:
        out["X-Riot-Token"] = "<redacted>"
    return out


async def raw_call(endpoint_id: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    entry = RAW_BY_ID.get(endpoint_id)
    if entry is None:
        raise LookupError(f"Unknown raw endpoint {endpoint_id!r}")

    call_params = dict(params or {})

    try:
        req = _build_raw_request(entry, call_params)
    except RuntimeError:
        raise
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}

    request_view = {
        "method": "GET",
        "url": req["url"],
        "query": req["query"],
        "headers": _redact_headers(req["headers"]),
    }

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                req["url"], params=req["query"], headers=req["headers"]
            )
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "request": request_view,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
        }
    elapsed = round((time.perf_counter() - t0) * 1000, 1)

    body_bytes = len(response.content)
    try:
        data = response.json()
        payload = truncate_json(data, max_bytes=RAW_PREVIEW_BYTES)
    except Exception:
        payload = {
            "text": response.text[:RAW_PREVIEW_BYTES],
            "truncated": body_bytes > RAW_PREVIEW_BYTES,
        }

    return {
        "ok": response.status_code < 400,
        "request": request_view,
        "response": {
            "status": response.status_code,
            "elapsed_ms": elapsed,
            "bytes": body_bytes,
            "content_type": response.headers.get("content-type"),
            **payload,
        },
    }
