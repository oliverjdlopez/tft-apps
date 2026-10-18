from __future__ import annotations

import base64
import asyncio
import json
from contextlib import AbstractContextManager
from types import SimpleNamespace

import pytest
from agents import MaxTurnsExceeded
from fastapi import FastAPI
from fastapi.testclient import TestClient
from api.routes.chat import ChatMessage, ChatRequest, router as chat_router
from domain.constants import AnthropicModels, OpenAIModels
from core.config import load_config
from services.chat_service import (
    chat_config,
    resolve_chat_assistant,
    stream_chat,
)
from domain.tools import get_tool
from domain.assistants.registry import current_registry
from domain.runtime import AssistantRunContext, ToolActivity
from domain.runtime.activity import ActivityRunHooks
from domain.tools.evidence import EvidenceStore
from domain.tools.context import CONTEXT_TOOL_GROUP
from domain.tools.db_tools.cohort_tools import COHORT_TOOL_GROUP
from domain.tools.db_tools.deltas import DELTA_TOOL_GROUP
from domain.tools.db_tools.ranking_tools import RANKING_TOOL_GROUP
from domain.tools.rolldown import PROBABILITY_TOOL_GROUP
from services.streaming import (
    STREAM_EVENT_PREFIX,
    STREAM_EVENT_SUFFIX,
    stream_agent_events,
    stream_event,
)


def test_resolve_chat_assistant_defaults_and_validates_header() -> None:
    """Resolve registered assistant names without changing the default root."""
    assert resolve_chat_assistant(None) == "chat"
    assert resolve_chat_assistant(" meta_expert ") == "meta_expert"

    with pytest.raises(LookupError, match="must name a registered assistant"):
        resolve_chat_assistant("   ")
    with pytest.raises(LookupError, match="Unknown chat assistant 'missing'"):
        resolve_chat_assistant("missing")


def test_discovery_routes_and_name_validation_do_not_build_agents(monkeypatch) -> None:
    """Browsing assistant metadata must work without constructing an SDK graph."""
    from api.routes.assistants import router as assistants_router

    registry = current_registry()

    def forbidden(*args, **kwargs):
        """Fail if a metadata operation crosses the execution boundary."""
        pytest.fail("Metadata lookup constructed an SDK agent")

    monkeypatch.setattr("domain.assistants.Assistant.from_name", forbidden)
    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(assistants_router)
    client = TestClient(app)
    config = client.get("/api/config")
    catalogue = client.get("/api/assistants")
    assert config.status_code == catalogue.status_code == 200
    assert config.json()["assistants"] == list(registry.assistant_names)
    rows = {row["name"]: row for row in catalogue.json()["assistants"]}
    assert rows["chat"]["description"] == registry.get_spec("chat").description
    assert rows["chat"]["tools"] == list(registry.tool_names["chat"])
    assert rows["chat"]["handoffs"] == ["data_analyst", "final_responder"]
    assert resolve_chat_assistant(" meta_expert ") == "meta_expert"
    with pytest.raises(LookupError, match="Unknown chat assistant"):
        resolve_chat_assistant("missing")


def test_chat_route_rejects_unknown_assistant_header_before_streaming() -> None:
    """Reject an unknown routed root at the HTTP boundary."""
    app = FastAPI()
    app.include_router(chat_router)

    response = TestClient(app).post(
        "/api/chat",
        headers={"X-Chat-Assistant": "missing"},
        json={"model": "unused", "messages": []},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown chat assistant 'missing'."}


def test_chat_config_includes_models_and_tools() -> None:
    config = chat_config()

    assert config["default_assistant"] == "chat"
    assert config["assistants"] == list(current_registry().assistant_names)
    assert config["default_model"] == load_config().models.openai_model
    assert [tool["name"] for tool in config["tools"]] == [
        *[tool.name for tool in CONTEXT_TOOL_GROUP.tools],
        *[tool.name for tool in RANKING_TOOL_GROUP.tools],
        *[tool.name for tool in PROBABILITY_TOOL_GROUP.tools],
        *[tool.name for tool in COHORT_TOOL_GROUP.tools],
        *[tool.name for tool in DELTA_TOOL_GROUP.tools],
        "present_evidence",
    ]
    assert [group["key"] for group in config["tool_groups"]] == [
        "query_cohorts",
        "deltas",
        "ranking",
        "probability",
        "context",
        "evidence",
    ]
    model_ids = {model["id"] for model in config["models"]}
    assert OpenAIModels.LATEST.value in model_ids
    assert len(model_ids) == len(config["models"])
    assert all(model["id"] in model["label"] for model in config["models"])
    assert OpenAIModels.CODEX_LATEST.value not in model_ids
    assert OpenAIModels.NANO.value not in model_ids
    assert AnthropicModels.SONNET.value in model_ids
    assert all(
        model["id"].startswith("claude-")
        for model in config["models"]
        if model["provider"] == "anthropic"
    )
    assert "skills" not in config


def test_chat_config_includes_database_runtime_status() -> None:
    """Browser configuration should carry the safe database warning payload."""
    database_status = {
        "available": False,
        "configured": False,
        "warning": "Database unavailable.",
    }

    config = chat_config(database_status=database_status)

    assert config["database"] == database_status


def test_builds_agents_sdk_tools_not_metadata_dicts() -> None:
    tool = get_tool("resolve_tft_names")

    assert not isinstance(tool, dict)
    assert getattr(tool, "name", "") == "resolve_tft_names"






def test_stream_event_round_trips_json_payload() -> None:
    encoded = stream_event({"type": "tool", "name": "example_chat_tool"})

    assert encoded.startswith(f"\n{STREAM_EVENT_PREFIX}")
    assert encoded.endswith(f"{STREAM_EVENT_SUFFIX}\n")

    payload = encoded.strip()
    payload = payload.removeprefix(STREAM_EVENT_PREFIX).removesuffix(
        STREAM_EVENT_SUFFIX
    )
    decoded = json.loads(base64.b64decode(payload).decode("utf-8"))

    assert decoded == {"type": "tool", "name": "example_chat_tool"}


def test_stream_agent_events_marks_completed_output_text_parts() -> None:
    """Emit one browser-visible boundary after an SDK text part's deltas."""

    class FakeResult:
        async def stream_events(self):
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(
                    type="response.output_text.delta",
                    delta="First ",
                ),
            )
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(
                    type="response.output_text.delta",
                    delta="part",
                ),
            )
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(type="response.output_text.done"),
            )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in stream_agent_events(
                FakeResult(),
                tools_by_name={},
                request_id="request-1",
                trace_id="trace-1",
            )
        ]

    chunks = asyncio.run(collect())
    payload = chunks[-1].strip().removeprefix(STREAM_EVENT_PREFIX).removesuffix(
        STREAM_EVENT_SUFFIX
    )

    assert chunks[:-1] == ["First ", "part"]
    assert json.loads(base64.b64decode(payload).decode("utf-8")) == {
        "type": "text_part_complete"
    }


def test_stream_agent_events_translates_tools_and_handoffs() -> None:
    class FakeResult:
        async def stream_events(self):
            yield SimpleNamespace(
                type="run_item_stream_event",
                name="tool_called",
                item=SimpleNamespace(
                    raw_item=SimpleNamespace(
                        name="rank_units",
                        call_id="call-1",
                        arguments='{"cost":4}',
                    )
                ),
            )
            yield SimpleNamespace(
                type="run_item_stream_event",
                name="tool_output",
                item=SimpleNamespace(call_id="call-1", output={"matches": 3}),
            )
            yield SimpleNamespace(
                type="run_item_stream_event",
                name="handoff_occurred",
                item=SimpleNamespace(target_agent=SimpleNamespace(name="analyst")),
            )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in stream_agent_events(
                FakeResult(),
                tools_by_name={
                    "rank_units": {"description": "Rank unit aggregates."}
                },
                request_id="request-1",
                trace_id="trace-1",
            )
        ]

    events = []
    for chunk in asyncio.run(collect()):
        payload = chunk.strip()
        payload = payload.removeprefix(STREAM_EVENT_PREFIX).removesuffix(
            STREAM_EVENT_SUFFIX
        )
        events.append(json.loads(base64.b64decode(payload).decode("utf-8")))

    assert events == [
        {
            "type": "tool",
            "name": "rank_units",
            "description": "Rank unit aggregates.",
            "arguments": {"cost": 4},
            "result": {"matches": 3},
            "result_preview": '{\n  "matches": 3\n}',
            "error": None,
        },
        {
            "type": "handoff",
            "name": "analyst",
            "description": "Conversation handed off to the analyst assistant.",
            "arguments": {},
            "result_preview": None,
            "error": None,
        },
    ]


def test_stream_chat_wraps_the_main_run_in_a_trace(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeTrace(AbstractContextManager):
        name = "chat_tft"
        trace_id = "trace_0123456789abcdef0123456789abcdef"

        def __enter__(self):
            captured["entered"] = True
            return self

        def __exit__(self, exc_type, exc, tb):
            captured["exited"] = True
            captured["exc_type"] = exc_type
            return False

    class FakeResult:
        async def stream_events(self):
            if False:
                yield None

    def fake_trace(workflow_name: str, *, metadata: dict[str, object]):
        captured["workflow_name"] = workflow_name
        captured["metadata"] = metadata
        return FakeTrace()

    monkeypatch.setattr("services.chat_service.trace", fake_trace)

    def selected_resources(**kwargs):
        """Provide an empty catalogue without model calls."""
        return {}

    monkeypatch.setattr(
        "domain.runtime.execution.select_resource_catalogues", selected_resources
    )

    def fake_run_streamed(agent, *, input, max_turns, context, hooks, run_config):
        assert isinstance(context, AssistantRunContext)
        assert isinstance(context.evidence, EvidenceStore)
        assert isinstance(hooks, ActivityRunHooks)
        captured["context"] = context
        captured["run_agent"] = agent
        captured["stream_input"] = input
        captured["max_turns"] = max_turns
        return FakeResult()

    monkeypatch.setattr("domain.runtime.execution.Runner.run_streamed", fake_run_streamed)

    body = ChatRequest(
        model="openai-latest",
        messages=[ChatMessage(role="user", content="What is the best comp?")],
    )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in stream_chat(
                [message.model_dump() for message in body.messages],
                body.system,
                body.model,
                model="gpt-5",
                max_tool_rounds=2,
                assistant_name="meta_expert",
            )
        ]

    chunks = asyncio.run(collect())
    assert captured["run_agent"].name == "meta_expert"
    assert len(chunks) == 1
    payload = chunks[0].strip().removeprefix(STREAM_EVENT_PREFIX).removesuffix(STREAM_EVENT_SUFFIX)
    assert json.loads(base64.b64decode(payload))['type'] == 'trace'
    assert captured["workflow_name"] == "chat_tft"
    assert captured["entered"] is True
    assert captured["exited"] is True
    assert captured["exc_type"] is None
    metadata = captured["metadata"]
    assert metadata["assistant"] == "meta_expert"
    assert metadata["model"] == "openai-latest"
    assert metadata["message_count"] == "1"
    assert metadata["direct_tool_names"] == ",".join(
        list(current_registry().tool_names["meta_expert"])
    )
    assert metadata["context_sources"] == ""
    assert captured["run_agent"].model == "gpt-5"
    assert captured["run_agent"].handoffs[0].model == "gpt-5"
    assert captured["context"].runtime.root_assistant == "meta_expert"
    assert captured["context"].resources.reads == {}
    assert captured["stream_input"] == [
        {"role": "user", "content": "What is the best comp?"}
    ]
    assert captured["max_turns"] == 3


@pytest.mark.parametrize("assistant_name", ["chat", "meta_expert"])
def test_stream_chat_uses_selected_assistant_for_tool_limit_fallback(
    monkeypatch, assistant_name: str,
) -> None:
    """Retain the selected graph and invocation evidence during tool-free fallback."""
    captured: dict[str, list[object]] = {
        "agent_names": [],
        "max_turns": [],
    }

    class FailingResult:
        async def stream_events(self):
            if False:
                yield None
            raise MaxTurnsExceeded("tool limit")

    class FinalResult:
        async def stream_events(self):
            yield SimpleNamespace(
                type="raw_response_event",
                data=SimpleNamespace(
                    type="response.output_text.delta",
                    delta="fallback response",
                ),
            )

    main_agent = None

    def fake_run_streamed(agent, *, input, max_turns, context, hooks, run_config):
        nonlocal main_agent
        if main_agent is None:
            main_agent = agent
        else:
            captured["agent_names"].append(agent.name)
            assert agent.tools == [] and agent.handoffs == []
            assert agent.spec is main_agent.spec
            assert agent.instructions.__self__ is agent
            assert agent.model_settings is main_agent.model_settings
        captured.setdefault("contexts", []).append(context)
        captured.setdefault("hooks", []).append(hooks)
        captured["max_turns"].append(max_turns)
        return FailingResult() if agent is main_agent else FinalResult()

    monkeypatch.setattr(
        "domain.runtime.execution.Runner.run_streamed",
        fake_run_streamed,
    )

    def selected_resources(**_kwargs):
        """Provide prepared resources without invoking resource selectors."""
        return {}

    monkeypatch.setattr(
        "domain.runtime.execution.select_resource_catalogues", selected_resources
    )

    request = ChatRequest(
        model="gpt-5",
        messages=[ChatMessage(role="user", content="Finish the analysis")],
    )

    async def collect() -> list[str]:
        return [
            chunk
            async for chunk in stream_chat(
                [message.model_dump() for message in request.messages],
                request.system,
                request.model,
                model="gpt-5",
                max_tool_rounds=2,
                assistant_name=assistant_name,
            )
        ]

    assert asyncio.run(collect())[-1] == "fallback response"
    expected = "chat_tft_final_response" if assistant_name == "chat" else f"{assistant_name}_final_response"
    assert captured["agent_names"] == [expected]
    assert captured["max_turns"] == [3, 1]
    assert isinstance(captured["contexts"][0], AssistantRunContext)
    assert isinstance(captured["contexts"][0].evidence, EvidenceStore)
    assert all(isinstance(hook, ActivityRunHooks) for hook in captured["hooks"])
    assert captured["contexts"][0] is captured["contexts"][1]


@pytest.mark.parametrize("fallback", [False, True])
def test_closing_chat_closes_active_adapter_and_finalizes_activity(monkeypatch, fallback):
    """HTTP consumer closure reaches the active main or fallback stream adapter."""
    contexts = []
    closed = []
    main_result, final_result = object(), object()

    def prepared(**_kwargs):
        """Provide resources without invoking a selector or external model."""
        return {}

    def run_streamed(agent, *, context, **_kwargs):
        """Capture the shared context for both runner entry points."""
        contexts.append(context)
        return main_result if len(contexts) == 1 else final_result

    async def events(result, *, run_context, **_kwargs):
        """Model an adapter suspended while the consumer processes a delta."""
        if fallback and result is main_result:
            raise MaxTurnsExceeded("tool limit")
        run_context.activity.calls["pending"] = ToolActivity("pending", "lookup")
        try:
            yield "delta"
            await asyncio.Event().wait()
        finally:
            closed.append(result)

    monkeypatch.setattr("domain.runtime.execution.select_resource_catalogues", prepared)
    monkeypatch.setattr("domain.runtime.execution.Runner.run_streamed", run_streamed)
    monkeypatch.setattr("services.chat_service.stream_agent_events", events)

    async def run():
        """Close chat after its first text delta rather than consuming to completion."""
        stream = stream_chat(
            [{"role": "user", "content": "Finish the analysis"}],
            None,
            "offline",
            model="offline",
            max_tool_rounds=1,
        )
        async for chunk in stream:
            if chunk == "delta":
                break
        await asyncio.wait_for(stream.aclose(), timeout=2)

    asyncio.run(run())
    assert closed == [final_result if fallback else main_result]
    assert len(contexts) == (2 if fallback else 1)
    assert all(context is contexts[0] for context in contexts)
    assert contexts[0].activity.calls["pending"].status == "cancelled"


@pytest.mark.parametrize('kind', ['reference', 'skill'])
def test_resource_source_events_follow_successful_reads(kind):
    """Source Activity events reflect actual reads instead of prompt selections."""
    resource = {'found': True, 'kind': kind, 'name': 'units', 'heading': 'Stage 2',
                'path': 'set18/units.md', 'content': 'Full resource', 'complete': True}

    class Result:
        """Supply one SDK tool-output event with serialized resource content."""
        async def stream_events(self):
            """Emit the event produced after the registered read tool completes."""
            yield SimpleNamespace(type='run_item_stream_event', name='tool_output',
                                  item=SimpleNamespace(tool_name='read_resource', call_id='read',
                                                       output=json.dumps(resource)))

    async def collect():
        """Collect the production streaming adapter's browser messages."""
        return [chunk async for chunk in stream_agent_events(
            Result(), tools_by_name={}, request_id='read-request', trace_id='read-trace')]

    chunks = asyncio.run(collect())
    events = [json.loads(base64.b64decode(chunk.strip().removeprefix(STREAM_EVENT_PREFIX)
                                        .removesuffix(STREAM_EVENT_SUFFIX))) for chunk in chunks]
    assert events[0]['type'] == ('context' if kind == 'reference' else 'skill')
    assert events[0]['path'] == resource['path']
    assert ('content' in events[0]) == (kind == 'reference')
    assert events[1]['type'] == 'tool' and events[1]['name'] == 'read_resource'
