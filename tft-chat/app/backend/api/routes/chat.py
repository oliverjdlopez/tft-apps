"""Chat HTTP routes."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import uuid4

from agents.extensions.models.litellm_model import LitellmModel
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.config import load_config
from domain.model_catalog import chat_model_spec
from services.chat_service import chat_config, resolve_chat_assistant, stream_chat
from services.utils import write_chat_timing

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


class ChatMessage(BaseModel):
    """One message accepted by the chat HTTP endpoint."""

    role: str
    content: str


class ChatRequest(BaseModel):
    """Validated chat HTTP request body."""

    model: str
    messages: list[ChatMessage]
    system: str | None = None


@router.get("/api/config")
def config(request: Request) -> dict:
    """Return browser-facing chat configuration."""
    database_status = getattr(request.app.state, "database_status", None)
    return chat_config(database_status=database_status)


@router.post("/api/chat", response_model=None)
async def chat(
    body: ChatRequest,
    assistant_header: Annotated[
        str | None,
        Header(alias="X-Chat-Assistant"),
    ] = None,
):
    """Validate a chat request and return its routed streamed response.

    Args:
        body: Model selection and conversation messages from the caller.
        assistant_header: Optional registered assistant selected by the
            ``X-Chat-Assistant`` request header.

    Returns:
        A streaming response, or a validation error before streaming begins.
    """
    try:
        assistant_name = resolve_chat_assistant(assistant_header)
    except LookupError as error:
        return JSONResponse({"detail": str(error)}, status_code=400)

    try:
        model_spec = chat_model_spec(body.model)
    except KeyError:
        return JSONResponse(
            {"detail": f"Unknown model {body.model!r}."}, status_code=400
        )

    config = load_config()
    is_anthropic = model_spec.provider == "anthropic"
    env_key = "ANTHROPIC_API_KEY" if is_anthropic else "OPENAI_API_KEY"
    key = (
        config.secrets.anthropic_api_key
        if is_anthropic
        else config.secrets.openai_api_key
    )
    if not key:
        return JSONResponse(
            {"detail": f"{env_key} is not set. Add it to your .env to use this model."},
            status_code=400,
        )
    if not is_anthropic:
        os.environ.setdefault("OPENAI_API_KEY", key)

    request_id = uuid4().hex
    request_started = time.perf_counter()
    messages = [message.model_dump() for message in body.messages]
    latest_user = next(
        (
            message.content.strip()
            for message in reversed(body.messages)
            if message.role == "user"
        ),
        "",
    )
    logger.info(
        "chat request accepted request_id=%s assistant=%s model=%s messages=%d latest_user_chars=%d",
        request_id,
        assistant_name,
        body.model,
        len(messages),
        len(latest_user),
    )

    async def generate() -> AsyncIterator[bytes]:
        """Encode chat chunks and record coarse request-stage timings."""
        timing: dict[str, Any] = {
            "request_id": request_id,
            "assistant": assistant_name,
            "model": body.model,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "started_at": request_started,
            "status": "interrupted",
        }
        try:
            async for chunk in stream_chat(
                messages,
                body.system,
                body.model,
                model=(
                    LitellmModel(model=f"anthropic/{body.model}", api_key=key)
                    if is_anthropic
                    else body.model
                ),
                max_tool_rounds=config.chat.max_tool_rounds,
                request_id=request_id,
                assistant_name=assistant_name,
                timing=timing,
            ):
                if "first_stream_chunk_ms" not in timing:
                    timing["first_stream_chunk_ms"] = round(
                        (time.perf_counter() - request_started) * 1000, 3
                    )
                yield chunk.encode("utf-8")
            timing["status"] = "complete"
        except Exception as error:  # noqa: BLE001 - errors must reach the browser stream.
            timing["status"] = "error"
            timing["error_type"] = type(error).__name__
            logger.exception(
                "chat stream failed request_id=%s model=%s elapsed_ms=%.1f",
                request_id,
                body.model,
                (time.perf_counter() - request_started) * 1000,
            )
            yield f"\n\n[error] {type(error).__name__}: {error}".encode("utf-8")
        finally:
            timing["total_ms"] = round(
                (time.perf_counter() - request_started) * 1000, 3
            )
            timing.pop("started_at", None)
            write_chat_timing(timing)

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
