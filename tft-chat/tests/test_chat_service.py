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
from domain.providers.context import (
    ContextFile,
    ContextSnippet,
    select_context_snippets,
)
from domain.providers.skills import SkillDefinition
from domain.tools import get_tool
from domain.assistants import (
    AssistantAgent, assistant_tool_names, create_assistant, list_assistants, prepare_resources,
)
from domain.runtime import AssistantRunContext, PreparedResources, ToolActivity
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
from domain.assistants.constants import AssistantName


def test_resolve_chat_assistant_defaults_and_validates_header() -> None:
    """Resolve registered assistant names without changing the default root."""
    assert resolve_chat_assistant(None) == AssistantName.CHAT
    assert resolve_chat_assistant(f' {AssistantName.META_EXPERT} ') == AssistantName.META_EXPERT

    with pytest.raises(LookupError, match="must name a registered assistant"):
        resolve_chat_assistant("   ")
    with pytest.raises(LookupError, match="Unknown chat assistant 'missing'"):
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

    assert config["default_assistant"] == AssistantName.CHAT
    assert config["assistants"] == list_assistants()
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


def test_prepare_resources_retains_recent_entity_for_follow_up() -> None:
    context_file = ContextFile(
        name="set-17-units",
        description="Set 17 units",
        body="# Units\n\n- **Riven** — adaptive bruiser",
        path="domain/resources/context/units.md",
        sets=("17",),
    )

    class FakeSkillProvider:
        async def aselect(self, query):
            assert query == "Tell me about Riven What about her items?"
            return []

    class FakeContextProvider:
        async def aselect(self, query, *, set_number=None, **_limits):
            return select_context_snippets(
                [context_file],
                query,
                set_number=set_number,
            )

        def render(self, references):
            return "\n".join(snippet.content for snippet in references)

    request = ChatRequest(
        model=OpenAIModels.LUNA.value,
        messages=[
            ChatMessage(role="user", content="Tell me about Riven"),
            ChatMessage(role="assistant", content="Riven is a bruiser."),
            ChatMessage(role="user", content="What about her items?"),
        ],
    )

    resources = asyncio.run(
        prepare_resources(
            [message.model_dump() for message in request.messages],
            set_number=17,
            context_provider=FakeContextProvider(),
            skill_provider=FakeSkillProvider(),
        )
    )

    assert [snippet.content for snippet in resources.references] == [
        "# Units\n\n- **Riven** — adaptive bruiser"
    ]


def test_prepare_resources_drops_history_for_unrelated_turn() -> None:
    queries: list[str] = []

    class FakeContextProvider:
        async def aselect(self, query, *, set_number=None, **_limits):
            queries.append(query)
            return []

    class FakeSkillProvider:
        async def aselect(self, query):
            assert query == "Hello, thanks!"
            return []

    messages = [
        ChatMessage(role="user", content="Tell me about Riven"),
        ChatMessage(role="assistant", content="Riven is a bruiser."),
        ChatMessage(role="user", content="Hello, thanks!"),
    ]
    asyncio.run(
        prepare_resources(
            [message.model_dump() for message in messages],
            set_number=17,
            context_provider=FakeContextProvider(),
            skill_provider=FakeSkillProvider(),
        )
    )

    assert queries == ["Hello, thanks!"]


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

    reference = ContextSnippet(
        context_file="units",
        path="domain/resources/context/units.md",
        heading="Riven",
        content="Riven is a bruiser.",
        line=42,
        score=9,
    )
    skill = SkillDefinition(
        name="compare-boards",
        description="Compare two board states.",
        body="Compare the boards.",
        path="domain/resources/skills/compare-boards/SKILL.md",
    )

    async def selected_resources(_messages, **kwargs):
        """Provide selections without invoking a model-backed selector."""
        return PreparedResources(query="What is the best comp?", references=(reference,), skills=(skill,))

    monkeypatch.setattr(
        "domain.assistants.agent.prepare_resources", selected_resources
    )

    def fake_create_assistant(name, **kwargs):
        captured["agent_name"] = name
        captured["create_kwargs"] = kwargs
        return create_assistant(name, **kwargs)

    monkeypatch.setattr("services.chat_service.create_assistant", fake_create_assistant)

    def fake_run_streamed(agent, *, input, max_turns, context, hooks):
        assert isinstance(context, AssistantRunContext)
        assert isinstance(context.evidence, EvidenceStore)
        assert isinstance(hooks, ActivityRunHooks)
        captured["context"] = context
        captured["run_agent"] = agent
        captured["stream_input"] = input
        captured["max_turns"] = max_turns
        return FakeResult()

    monkeypatch.setattr("services.chat_service.Runner.run_streamed", fake_run_streamed)

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
                assistant_name=AssistantName.META_EXPERT,
            )
        ]

    chunks = asyncio.run(collect())
    assert captured["agent_name"] == AssistantName.META_EXPERT
    assert captured["run_agent"].name == AssistantName.META_EXPERT
    assert len(chunks) == 3
    decoded_events = []
    for chunk in chunks:
        payload = chunk.strip()
        payload = payload.removeprefix(STREAM_EVENT_PREFIX).removesuffix(
            STREAM_EVENT_SUFFIX
        )
        decoded_events.append(json.loads(base64.b64decode(payload).decode("utf-8")))
    assert decoded_events == [
        {
            "type": "context",
            "name": "Riven",
            "description": "Context chunk selected for this response.",
            "path": "domain/resources/context/units.md",
            "line": 42,
            "content": "Riven is a bruiser.",
        },
        {
            "type": "skill",
            "name": "compare-boards",
            "description": "Compare two board states.",
            "path": "domain/resources/skills/compare-boards/SKILL.md",
        },
        {
            "type": "trace",
            "name": "chat_tft",
            "trace_id": "trace_0123456789abcdef0123456789abcdef",
        },
    ]
    assert captured["workflow_name"] == "chat_tft"
    assert captured["entered"] is True
    assert captured["exited"] is True
    assert captured["exc_type"] is None
    metadata = captured["metadata"]
    assert metadata["assistant"] == AssistantName.META_EXPERT
    assert metadata["model"] == "openai-latest"
    assert metadata["message_count"] == "1"
    assert metadata["direct_tool_names"] == ",".join(
        assistant_tool_names(AssistantName.META_EXPERT)
    )
    assert metadata["context_sources"] == "domain/resources/context/units.md"
    create_kwargs = captured["create_kwargs"]
    assert create_kwargs == {"model": "gpt-5"}
    assert captured["context"].runtime.root_assistant == AssistantName.META_EXPERT
    assert captured["context"].resources.references == (reference,)
    assert captured["stream_input"] == [
        {"role": "user", "content": "What is the best comp?"}
    ]
    assert captured["max_turns"] == 3


@pytest.mark.parametrize("assistant_name", [AssistantName.CHAT, AssistantName.META_EXPERT])
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

    main_agent = create_assistant(assistant_name, model="gpt-5")

    def fake_run_streamed(agent, *, input, max_turns, context, hooks):
        captured.setdefault("contexts", []).append(context)
        captured.setdefault("hooks", []).append(hooks)
        captured["max_turns"].append(max_turns)
        if agent is not main_agent:
            captured["agent_names"].append(agent.name)
            assert isinstance(agent, AssistantAgent)
            assert agent.tools == [] and agent.handoffs == []
            assert agent.instructions is main_agent.instructions
            assert agent.spec is main_agent.spec
            assert agent.is_root is True
            assert agent.context_provider is main_agent.context_provider
            assert agent.skill_provider is main_agent.skill_provider
        return FailingResult() if agent is main_agent else FinalResult()

    monkeypatch.setattr(
        "services.chat_service.Runner.run_streamed",
        fake_run_streamed,
    )
    monkeypatch.setattr(
        "services.chat_service.create_assistant",
        lambda _name, **_kwargs: main_agent,
    )

    async def selected_resources(_messages, **_kwargs):
        """Provide prepared resources without invoking resource selectors."""
        return PreparedResources(query="Finish the analysis")

    monkeypatch.setattr(
        "domain.assistants.agent.prepare_resources", selected_resources
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
    expected = AssistantName.CHAT_FINAL_RESPONSE if assistant_name == AssistantName.CHAT else f"{assistant_name}_final_response"
    assert captured["agent_names"] == [expected]
    assert captured["max_turns"] == [3, 1]
    assert isinstance(captured["contexts"][0], AssistantRunContext)
    assert isinstance(captured["contexts"][0].evidence, EvidenceStore)
    assert captured["hooks"][0] is captured["hooks"][1]
    assert captured["contexts"][0] is captured["contexts"][1]


@pytest.mark.parametrize("fallback", [False, True])
def test_closing_chat_closes_active_adapter_and_finalizes_activity(monkeypatch, fallback):
    """HTTP consumer closure reaches the active main or fallback stream adapter."""
    contexts = []
    closed = []
    main_agent = create_assistant(AssistantName.CHAT, instructions="DURABLE ROOT", model="offline")
    main_result, final_result = object(), object()

    async def prepared(_messages, **_kwargs):
        """Provide resources without invoking a selector or external model."""
        return PreparedResources(query="Finish the analysis")

    def run_streamed(agent, *, context, **_kwargs):
        """Capture the shared context for both runner entry points."""
        contexts.append(context)
        return main_result if agent is main_agent else final_result

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

    monkeypatch.setattr("domain.assistants.agent.prepare_resources", prepared)
    monkeypatch.setattr("services.chat_service.create_assistant", lambda *args, **kwargs: main_agent)
    monkeypatch.setattr("services.chat_service.Runner.run_streamed", run_streamed)
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
