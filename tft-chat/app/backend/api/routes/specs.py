"""Assistant specification editor routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services import spec_service

router = APIRouter(prefix="/api/specs", tags=["specs"])


class SpecDocumentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(max_length=1_000_000)
    revision: str = Field(min_length=64, max_length=64)


@router.get("")
def spec_workspace() -> dict[str, Any]:
    try:
        return spec_service.workspace()
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("/documents/{document_id}")
def spec_document(document_id: str) -> dict[str, Any]:
    try:
        return spec_service.read_document(document_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="editable spec not found") from None
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.put("/documents/{document_id}")
async def update_spec_document(document_id: str, body: SpecDocumentBody) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            spec_service.save_document, document_id, body.content, body.revision
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="editable spec not found") from None
    except spec_service.DocumentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
