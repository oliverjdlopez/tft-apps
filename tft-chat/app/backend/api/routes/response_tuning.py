"""Developer route for branching stored OpenAI Responses API responses."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from core.config import load_config
from services.response_tuning_service import run_response_continuation

router = APIRouter(tags=["response-tuning"])


class ResponseContinuationRequest(BaseModel):
    """Validated input for one developer-facing response continuation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    response_id: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=100_000)
    model: str | None = Field(default=None, max_length=256)
    instructions: str | None = Field(default=None, max_length=100_000)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_output_tokens: int | None = Field(default=None, ge=1, le=100_000)


@router.post("/api/response-tuning/continue")
async def continue_response(body: ResponseContinuationRequest) -> dict:
    """Branch a stored response without exposing the OpenAI API key to the UI."""
    if not load_config().secrets.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is not set. Add it to .env before running a continuation.",
        )
    return await asyncio.to_thread(
        run_response_continuation,
        body.response_id,
        body.message,
        model=body.model or None,
        instructions=body.instructions,
        temperature=body.temperature,
        max_output_tokens=body.max_output_tokens,
    )
