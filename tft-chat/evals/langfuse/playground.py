"""Run editable native Playground messages through the actual ChatTFT graph."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from .models import PlaygroundRequest
from .utils import playground_assistants, playground_payload, playground_stream

router = APIRouter(prefix="/v1")
logger = logging.getLogger(__name__)
# Each worker can make several paid calls; cap active workers, including those
# whose browser disconnected while the bounded subprocess finishes.
slots = threading.BoundedSemaphore(4)


@router.get("/models")
def models() -> dict:
    """Expose assistant names as selectable models in an OpenAI connection."""
    return {"object": "list", "data": [
        {"id": f"chattft/{name}", "object": "model", "created": 0, "owned_by": "chattft"}
        for name in playground_assistants()
    ]}


def run_playground(client, payload: dict, model: str) -> dict:
    """Execute one isolated graph and retain editable inputs and inspection evidence."""
    from evals.utils import isolated_operation

    try:
        with client.start_as_current_observation(
            name="chattft-playground", as_type="span", input={"messages": payload["playground_messages"]},
            metadata={"source": "playground", "assistant": payload["config"]["assistant"],
                      "prompt_overrides": payload["config"]["prompt_candidates"],
                      "model_settings": payload["config"].get("model_settings", {})},
        ) as observation:
            trace_url = client.get_trace_url(trace_id=observation.trace_id)
            # V4's trace overview has no root I/O. Select the actual observation
            # so the inspection URL immediately shows the editable request.
            if trace_url:
                trace_url += f"?observation={observation.id}"
            try:
                result = isolated_operation(payload, timeout=180)
                if result.get("error"):
                    raise RuntimeError(result["error"])
                output = result.get("output", "")
                text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False, indent=2)
                observation.update(output=output, metadata=result.get("metadata", {}))
                usage = result.get("token_usage", {})
                return {
                    "id": "chatcmpl-" + uuid4().hex, "object": "chat.completion", "created": int(time.time()),
                    "model": model, "choices": [{"index": 0, "message": {"role": "assistant",
                        "content": text + f"\n\n---\nInspect ChatTFT run: tools, handoffs, and prompts\n{trace_url}"},
                        "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": usage.get("prompt", 0), "completion_tokens": usage.get("completion", 0),
                              "total_tokens": usage.get("total", 0)},
                }
            except Exception as exc:
                observation.update(level="ERROR", status_message=str(exc))
                # Error details live in the private trace; do not leak connection
                # strings or provider credentials through an upstream exception.
                raise RuntimeError(f"ChatTFT run failed. Inspect {trace_url}") from exc
    finally:
        try:
            client.flush()
        finally:
            slots.release()


@router.post("/chat/completions")
async def complete(request: Request):
    """Validate before paid execution and return ordinary or streaming completions."""
    try:
        body = PlaygroundRequest.model_validate(await request.json())
        payload = playground_payload(body)
    except (ValueError, ValidationError) as exc:
        return JSONResponse({"error": {"message": str(exc), "type": "invalid_request_error"}}, status_code=400)
    if not slots.acquire(blocking=False):
        return JSONResponse({"error": {"message": "Four ChatTFT runs are active; retry after one finishes.",
                                       "type": "rate_limit_error"}}, status_code=429)
    task = asyncio.create_task(asyncio.to_thread(run_playground, request.app.state.service.client, payload, body.model))
    # Retrieve exceptions even if a streaming client disconnects before completion.
    task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    if body.stream:
        return StreamingResponse(playground_stream(task, body), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    try:
        return await asyncio.shield(task)
    except Exception as exc:
        logger.exception("Playground run failed")
        return JSONResponse({"error": {"message": str(exc), "type": "backend_error"}}, status_code=502)


def configure_connection(workspace, token: str) -> None:
    """Install the owned backend connection without touching the judge provider."""
    workspace.request("PUT", "llm-connections", json={
        "provider": "ChatTFT backend", "adapter": "openai", "secretKey": token,
        "baseURL": "http://experiments/v1", "customModels": [row["id"] for row in models()["data"]],
        "withDefaultModels": False,
    })
