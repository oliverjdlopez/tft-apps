"""Disposable real chat/SDK/SQL/evidence routes for production-browser journeys."""

from __future__ import annotations

import ast
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tft-chat"), str(ROOT / "tft-chat/app/backend"), str(ROOT / "tft-chat/app/backend/src"), str(ROOT / "tft-chat/tests")]

from agents import OpenAIResponsesModel, set_tracing_disabled
from fastapi import Request
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.routes import chat
from core.config import load_config
from db.models import Base, AnalysisScope, AnalysisFactBuild, UnitStatQueryTable, ALL_STARS, ANALYSIS_FACT_SCHEMA_VERSION
from domain.assistants import Assistant
from devtools.assistants import registry_from_files
from domain.tools import get_tool
from domain.tools.db_tools import ranking_tools
from domain.tools.evidence.models import DisplaySpec
from services import chat_service
from scripts.transcription.media_store.router import router as shared_router

# Reuse Stage 1's production-built Flowchart fixture and disposable store.
from flowchart_smoke_server import app

set_tracing_disabled(True)
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine)
with Session(engine) as session:
    scope = AnalysisScope(patch="synthetic", queue_id=1100, tft_set_number=18, is_active=True, status="ready", universe_boards=200)
    session.add(scope)
    session.flush()
    session.add(AnalysisFactBuild(scope_id=scope.scope_id, schema_version=ANALYSIS_FACT_SCHEMA_VERSION, status="ready", board_count=200))
    session.add(UnitStatQueryTable(scope_id=scope.scope_id, unit_name="Fixture Carry", star_level=ALL_STARS,
                                  tft_set_number=18, cost=4, games=100, avg_placement=Decimal("3.5"),
                                  top4_rate=Decimal("0.625"), win_rate=Decimal("0.25"), pick_rate=Decimal("0.5"), universe_games=200))
    session.commit()

registry = registry_from_files({"chat": {"system.md": "Use the fixture ranking and present its evidence.",
    "agent.json": json.dumps({"tools": {"groups": ["ranking", "evidence"]}, "context": {"repository": False}, "skills": []})}})


class FixtureAssistant(Assistant):
    """Use an isolated specification tree with actual registered application tools."""

    def __init__(self, name, **kwargs):
        """Freeze the fixture registry while preserving normal invocation setup."""
        super().__init__(name, registry=registry, **kwargs)

    @staticmethod
    def names():
        """Expose only the isolated chat root to the production configuration route."""
        return ["chat"]


async def run_database(ctx, operation, **kwargs):
    """Replace only external database acquisition; run the actual ranking SQL."""
    with Session(engine) as session:
        return operation(session)


ranking_tools.run_db_tool = run_database
chat_service.Assistant = FixtureAssistant
config = load_config()
config = replace(config, secrets=replace(config.secrets, openai_api_key="local-fixture"),
                 chat=replace(config.chat, langfuse_tracing=False))
chat.load_config = lambda: config
chat_service.load_config = lambda: config
original_stream = chat_service.stream_chat
metrics = {"model_requests": 0, "rank_calls": 0, "presentations": 0, "cancelled": 0}


async def stream(messages, system, model_name, **kwargs):
    """Point the normal SDK runner at the in-process mock HTTP model boundary."""
    client = AsyncOpenAI(api_key="fixture", base_url=os.environ["JOURNEY_BASE_URL"] + "/v1", max_retries=0)
    kwargs["model"] = OpenAIResponsesModel(model_name, client)
    try:
        async for chunk in original_stream(messages, system, model_name, **kwargs):
            yield chunk
    except asyncio.CancelledError:
        metrics["cancelled"] += 1
        raise
    finally:
        await client.close()


chat.stream_chat = stream
# Replace only the fixture config route; keep the real chat HTTP route.
app.router.routes = [route for route in app.router.routes if getattr(route, "path", None) not in ("/api/config", "/{path:path}")]
app.include_router(chat.router)
app.include_router(shared_router)


@app.get("/__test__/metrics")
def observed_metrics():
    """Expose counts used to prove tool execution and cancellation in the browser."""
    return metrics


@app.get("/api/overview")
def overview():
    """Keep the unrelated status panel independent of application RDS startup."""
    return {"db": {"scoped_boards": 200, "raw_boards": 200}}


@app.post("/v1/responses")
async def model_response(request: Request):
    """Emit valid Responses SSE with real ranking and evidence tool calls."""
    body = await request.json()
    metrics["model_requests"] += 1
    outputs = []
    for item in body.get("input", []):
        if isinstance(item, dict) and item.get("type") == "function_call_output":
            raw = item.get("output", "")
            try:
                outputs.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                try:
                    outputs.append(ast.literal_eval(raw))
                except (ValueError, SyntaxError):
                    pass
    ranked = next((item for item in outputs if isinstance(item, dict) and "evidence" in item), None)
    presented = any(isinstance(item, dict) and item.get("presented") for item in outputs)
    cancelled = "cancel fixture" in json.dumps(body.get("input", [])).lower()
    if ranked and not presented:
        metrics["presentations"] += 1
        spec = DisplaySpec(evidence_ref=ranked["evidence"]["evidence_ref"], dataset_ref="rows", kind="interactive_table",
                           title="Synthetic unit outcomes", columns=["unit_name", "games", "top4_rate"])
        name, arguments = "present_evidence", {"request": spec.model_dump()}
    elif not ranked and not presented and not cancelled:
        metrics["rank_calls"] += 1
        tool = get_tool("rank_units")
        arguments = {key: schema.get("default") for key, schema in tool.params_json_schema["properties"].items()}
        arguments.update(group_by_star_level=False, sort_by="games", sort_direction="auto", range=[0, 10])
        name = "rank_units"
    else:
        name, arguments = None, None
    text = "Synthetic evidence supports this fixture answer. Café ☕"
    item = ({"id": "fc_" + uuid4().hex, "type": "function_call", "name": name, "call_id": "call_" + uuid4().hex,
             "arguments": json.dumps(arguments), "status": "completed"} if name else
            {"id": "msg_" + uuid4().hex, "type": "message", "role": "assistant", "status": "completed",
             "content": [{"type": "output_text", "text": text, "annotations": []}]})
    response = {"id": "resp_" + uuid4().hex, "object": "response", "created_at": int(time.time()), "status": "completed",
                "model": body["model"], "output": [item], "parallel_tool_calls": True, "tools": [], "tool_choice": "auto",
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}
    events = [{"type": "response.created", "response": {**response, "status": "in_progress", "output": []}},
              {"type": "response.output_item.added", "output_index": 0,
               "item": {**item, "status": "in_progress", **({"arguments": ""} if name else {"content": []})}}]
    if name:
        events.append({"type": "response.function_call_arguments.delta", "item_id": item["id"], "output_index": 0, "delta": item["arguments"]})
        events.append({"type": "response.function_call_arguments.done", "item_id": item["id"], "output_index": 0, "arguments": item["arguments"]})
    else:
        events.extend([
            {"type": "response.content_part.added", "item_id": item["id"], "output_index": 0, "content_index": 0,
             "part": {"type": "output_text", "text": "", "annotations": []}},
            {"type": "response.output_text.delta", "item_id": item["id"], "output_index": 0, "content_index": 0, "delta": text},
            {"type": "response.output_text.done", "item_id": item["id"], "output_index": 0, "content_index": 0, "text": text}])
    events.extend([{"type": "response.output_item.done", "output_index": 0, "item": item},
                   {"type": "response.completed", "response": response}])

    async def frames():
        """Keep cancellation observable without contacting an external provider."""
        for index, event in enumerate(events):
            yield f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': index})}\n\n"
            if cancelled and index == 0:
                await asyncio.sleep(30)

    return StreamingResponse(frames(), media_type="text/event-stream")


@app.get("/{path:path}")
def index(path: str):
    """Serve the same production bundle used by desktop and browser installations."""
    from fastapi.responses import FileResponse
    if path.startswith("api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Fixture route not found"}, status_code=404)
    return FileResponse(ROOT / "tft-chat/app/frontend/dist/index.html")
