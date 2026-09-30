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
    _build_chat_instructions,
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
from domain.assistants import assistant_tool_names, list_assistants
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


def test_build_chat_instructions_retains_recent_entity_for_follow_up() -> None:
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

    _root, _handoffs, references, _skills = asyncio.run(
        _build_chat_instructions(
            [message.model_dump() for message in request.messages],
            request.system,
            context_provider=FakeContextProvider(),
            skill_provider=FakeSkillProvider(),
        )
    )

    assert [snippet.content for snippet in references] == [
        "# Units\n\n- **Riven** — adaptive bruiser"
    ]


def test_build_chat_instructions_drops_history_for_unrelated_turn() -> None:
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
        _build_chat_instructions(
            [message.model_dump() for message in messages],
            None,
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

    async def empty_instructions(_messages, _system, *, assistant_name):
        assert assistant_name == "meta_expert"
        return "CHAT", {}, (reference,), (skill,)

    monkeypatch.setattr(
        "services.chat_service._build_chat_instructions", empty_instructions
    )

    def fake_create_assistant(name, **kwargs):
        captured["agent_name"] = name
        captured["create_kwargs"] = kwargs
        return SimpleNamespace(name=name)

    monkeypatch.setattr("services.chat_service.create_assistant", fake_create_assistant)

    def fake_run_streamed(agent, *, input, max_turns, context):
        assert isinstance(context, EvidenceStore)
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
                assistant_name="meta_expert",
            )
        ]

    chunks = asyncio.run(collect())
    assert captured["agent_name"] == "meta_expert"
    assert captured["run_agent"].name == "meta_expert"
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
    assert metadata["assistant"] == "meta_expert"
    assert metadata["model"] == "openai-latest"
    assert metadata["message_count"] == "1"
    assert metadata["direct_tool_names"] == ",".join(
        assistant_tool_names("meta_expert")
    )
    assert metadata["context_sources"] == "domain/resources/context/units.md"
    assert captured["create_kwargs"] == {
        "instructions": "CHAT",
        "model": "gpt-5",
        "instructions_by_name": {},
    }
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

    class FakeAgent:
        def __init__(self, **kwargs):
            self.name = kwargs["name"]
            captured["agent_names"].append(self.name)
            assert kwargs["tools"] == [] and kwargs["handoffs"] == []

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

    monkeypatch.setattr("services.chat_service.Agent", FakeAgent)
    main_agent = SimpleNamespace(name=assistant_name)

    def fake_run_streamed(agent, *, input, max_turns, context):
        captured.setdefault("contexts", []).append(context)
        captured["max_turns"].append(max_turns)
        return FailingResult() if agent is main_agent else FinalResult()

    monkeypatch.setattr(
        "services.chat_service.Runner.run_streamed",
        fake_run_streamed,
    )
    monkeypatch.setattr(
        "services.chat_service.create_assistant",
        lambda _name, **_kwargs: main_agent,
    )

    async def empty_instructions(_messages, _system, **_kwargs):
        """Check routed instruction selection without invoking resource selectors."""
        assert _kwargs["assistant_name"] == assistant_name
        return "CHAT", {}, (), ()

    monkeypatch.setattr(
        "services.chat_service._build_chat_instructions", empty_instructions
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
    assert isinstance(captured["contexts"][0], EvidenceStore)
    assert captured["contexts"][0] is captured["contexts"][1]
