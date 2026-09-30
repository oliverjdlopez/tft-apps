"""Data and tool explorer HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services import display_service

router = APIRouter(tags=["data"])


class CallToolBody(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class RawCallBody(BaseModel):
    id: str
    params: dict[str, Any] = Field(default_factory=dict)


@router.get("/api/overview")
def overview() -> dict[str, Any]:
    return display_service.overview()


@router.get("/api/models")
def models() -> dict[str, Any]:
    return display_service.models()


@router.get("/api/db")
def db(sample: int = 0) -> dict[str, Any]:
    return display_service.db(sample=sample)


@router.get("/api/db/{table}/rows")
def db_table_rows(
    table: str,
    limit: int = 50,
    offset: int = 0,
    sort: str | None = None,
    direction: str = "asc",
    q: str = "",
) -> dict[str, Any]:
    try:
        return display_service.db_table_rows(
            table, limit=limit, offset=offset, sort=sort, direction=direction, q=q
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get("/api/tools")
def tool_catalog() -> dict[str, Any]:
    return display_service.tool_catalog()


@router.post("/api/tools/call")
async def tool_call(body: CallToolBody) -> dict[str, Any]:
    """Invoke a registered model-facing tool from the browser explorer."""
    return await display_service.tool_call(body.name, body.arguments)


@router.get("/api/raw/catalog")
def raw_catalog() -> dict[str, Any]:
    return display_service.raw_catalog()


@router.post("/api/raw/call")
async def raw_call(body: RawCallBody) -> dict[str, Any]:
    try:
        return await display_service.raw_call(body.id, body.params)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
