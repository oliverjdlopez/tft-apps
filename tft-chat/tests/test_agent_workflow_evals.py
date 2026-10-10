"""Regression contracts for the trace and typed database adapters."""
from __future__ import annotations
import json
from types import SimpleNamespace
import pytest
from evals import database as eval_database
from core.config import DatabaseTarget
from db.session import resolve_database_target as resolve_runtime_database_target
from evals.trace import EvalTrace, Handoff, TraceEvent, ToolCall, TraceCheckResult, evaluate_trace_check, extract_trace, trace_from_dict
from domain.assistants.constants import AssistantName

def _fake_tool_call(
    name: str,
    arguments: str = "{}",
    *,
    agent: str | None = None,
    call_id: str | None = None,
) -> SimpleNamespace:
    """Build one SDK-shaped tool call item for offline eval tests.

    Args:
        name: Tool name exposed on the fake call.
        arguments: Raw JSON arguments captured for trace evaluation.
        agent: Optional assistant name that owns the tool call.
        call_id: Optional identity used to pair the call with its output.

    Returns:
        A minimal object accepted by the trace extractor.
    """
    return SimpleNamespace(
        type="tool_call_item",
        tool_name=name,
        raw_item={"name": name, "arguments": arguments, "call_id": call_id},
        agent=None if agent is None else SimpleNamespace(name=agent),
    )


def _fake_tool_output(call_id: str, output: object) -> SimpleNamespace:
    """Build one SDK-shaped tool output item for offline eval tests.

    Args:
        call_id: Identity of the corresponding tool call.
        output: JSON-compatible tool result.

    Returns:
        A minimal output object accepted by the trace extractor.
    """
    return SimpleNamespace(
        type="tool_call_output_item",
        raw_item={"call_id": call_id},
        call_id=call_id,
        output=output,
    )


def _fake_handoff(source: str, target: str) -> SimpleNamespace:
    return SimpleNamespace(
        type="handoff_output_item",
        source_agent=SimpleNamespace(name=source),
        target_agent=SimpleNamespace(name=target),
    )


def _fake_run_result(
    output: str,
    *,
    tool_names: tuple[str, ...] = (),
    handoffs: tuple[tuple[str, str], ...] = (),
    final_agent: str = AssistantName.CHAT,
    turns: int = 3,
) -> SimpleNamespace:
    items = [_fake_tool_call(name) for name in tool_names]
    items.extend(_fake_handoff(source, target) for source, target in handoffs)
    return SimpleNamespace(
        final_output=output,
        new_items=items,
        last_agent=SimpleNamespace(name=final_agent),
        raw_responses=[object()] * turns,
    )


class _FakeAgent:
    def __init__(self, run_result_factory):
        self.run_result_factory = run_result_factory


def test_trace_checks_are_deterministic() -> None:
    trace = EvalTrace(tool_calls=[ToolCall(name="rank_units")])

    assert evaluate_trace_check(
        {"type": "tool_called", "value": "rank_units"}, trace
    ).passed
    assert not evaluate_trace_check(
        {"type": "tool_called", "value": "missing_tool"}, trace
    ).passed


def test_tool_checks_match_argument_subsets_with_exact_scalar_shapes() -> None:
    """Match requested tool arguments while tolerating unrelated defaults."""
    trace = EvalTrace(
        tool_calls=[
            ToolCall(
                name="rank_units",
                arguments=json.dumps(
                    {
                        "cost": 4,
                        "item": None,
                        "range": [0, 5],
                        "sort_by": "games",
                    }
                ),
            )
        ]
    )

    matching = evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "arguments": {"cost": 4, "range": [0, 5]},
        },
        trace,
    )
    wrong_sort = evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "arguments": {"sort_by": "avg_placement"},
        },
        trace,
    )
    wrong_shape = evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "arguments": {"cost": [4]},
        },
        trace,
    )
    wrong_json_type = evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "arguments": {"cost": True},
        },
        trace,
    )

    assert matching.passed
    assert not wrong_sort.passed
    assert not wrong_shape.passed
    assert not wrong_json_type.passed


def test_tool_checks_reject_invalid_argument_expectations() -> None:
    """Reject empty subsets and argument checks that lose call ordering."""
    with pytest.raises(ValueError, match="arguments must be a non-empty object"):
        evaluate_trace_check(
            {"type": "tool_called", "value": "rank_units", "arguments": {}},
            EvalTrace(),
        )
    with pytest.raises(ValueError, match="cannot be combined with after_handoff"):
        evaluate_trace_check(
            {
                "type": "tool_called",
                "value": "rank_units",
                "arguments": {"cost": 4},
                "after_handoff": AssistantName.DATA_ANALYST,
            },
            EvalTrace(),
        )


def test_tool_argument_resolved_tracks_candidate_into_later_call() -> None:
    """Accept dynamic stored names while requiring resolver-to-tool dataflow."""
    trace = EvalTrace(
        tool_calls=[
            ToolCall(
                name="resolve_tft_names",
                arguments=json.dumps({"names": ["jinx"]}),
                agent=AssistantName.CHAT,
                output=json.dumps(
                    {
                        "results": [
                            {
                                "query": "jinx",
                                "matches": [{"name": "Jinx", "kind": "unit"}],
                            }
                        ]
                    }
                ),
            ),
            ToolCall(
                name="rank_unit_loadouts",
                arguments=json.dumps({"unit": "Jinx", "range": [0, 5]}),
                agent=AssistantName.CHAT,
            ),
        ]
    )

    result = evaluate_trace_check(
        {
            "type": "tool_argument_resolved",
            "value": "rank_unit_loadouts",
            "agent": AssistantName.CHAT,
            "query": "jinx",
            "argument": "unit",
            "arguments": {"range": [0, 5]},
        },
        trace,
    )

    assert result.passed


def test_tool_argument_resolved_rejects_memory_and_wrong_order() -> None:
    """Reject hard-coded or pre-resolution entity arguments."""
    resolution = ToolCall(
        name="resolve_tft_names",
        arguments=json.dumps({"names": ["jinx"]}),
        output=json.dumps(
            {
                "results": [
                    {"query": "jinx", "matches": [{"name": "Jinx"}]}
                ]
            }
        ),
    )
    hard_coded = ToolCall(
        name="rank_unit_loadouts",
        arguments=json.dumps({"unit": "TFT17_Jinx", "range": [0, 5]}),
    )
    config = {
        "type": "tool_argument_resolved",
        "value": "rank_unit_loadouts",
        "query": "jinx",
        "argument": "unit",
    }

    assert not evaluate_trace_check(
        config, EvalTrace(tool_calls=[resolution, hard_coded])
    ).passed
    assert not evaluate_trace_check(
        config,
        EvalTrace(
            tool_calls=[
                ToolCall(
                    name="rank_unit_loadouts",
                    arguments=json.dumps({"unit": "Jinx"}),
                ),
                resolution,
            ]
        ),
    ).passed


def test_tool_argument_resolved_rejects_invalid_configuration() -> None:
    """Fail manifest preflight for missing fields or incompatible ordering."""
    with pytest.raises(ValueError, match="query must be a non-empty string"):
        evaluate_trace_check(
            {
                "type": "tool_argument_resolved",
                "value": "rank_units",
                "argument": "item",
            },
            EvalTrace(),
        )
    with pytest.raises(ValueError, match="cannot be combined with after_handoff"):
        evaluate_trace_check(
            {
                "type": "tool_argument_resolved",
                "value": "rank_units",
                "query": "rageblade",
                "argument": "item",
                "after_handoff": AssistantName.DATA_ANALYST,
            },
            EvalTrace(),
        )


def test_tool_checks_can_require_agent_ownership_after_handoff() -> None:
    """Reject a tool call that is owned by the wrong agent or occurs too early."""
    trace = EvalTrace(
        tool_calls=[
            ToolCall(name="rank_units", agent=AssistantName.CHAT),
            ToolCall(name="rank_units", agent=AssistantName.DATA_ANALYST),
        ],
        handoffs=[Handoff(source=AssistantName.CHAT, target=AssistantName.DATA_ANALYST)],
        events=[
            TraceEvent(type="tool_call", agent=AssistantName.CHAT, tool="rank_units"),
            TraceEvent(
                type="handoff",
                agent=AssistantName.CHAT,
                source=AssistantName.CHAT,
                target=AssistantName.DATA_ANALYST,
            ),
            TraceEvent(
                type="tool_call",
                agent=AssistantName.DATA_ANALYST,
                tool="rank_units",
            ),
        ],
    )

    assert evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "agent": AssistantName.DATA_ANALYST,
            "after_handoff": AssistantName.DATA_ANALYST,
        },
        trace,
    ).passed
    assert not evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "agent": AssistantName.CHAT,
            "after_handoff": AssistantName.DATA_ANALYST,
        },
        trace,
    ).passed


def test_tool_check_does_not_infer_order_from_aggregate_fields() -> None:
    """Require ordered events when a check claims a post-handoff tool call."""
    trace = EvalTrace(
        tool_calls=[ToolCall(name="rank_units", agent=AssistantName.DATA_ANALYST)],
        handoffs=[Handoff(source=AssistantName.CHAT, target=AssistantName.DATA_ANALYST)],
        # This intentionally places the tool before the handoff.
        events=[
            TraceEvent(type="tool_call", agent=AssistantName.DATA_ANALYST, tool="rank_units"),
            TraceEvent(
                type="handoff",
                agent=AssistantName.CHAT,
                source=AssistantName.CHAT,
                target=AssistantName.DATA_ANALYST,
            ),
        ],
    )

    result = evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "agent": AssistantName.DATA_ANALYST,
            "after_handoff": AssistantName.DATA_ANALYST,
        },
        trace,
    )

    assert not result.passed


def test_tool_checks_can_require_agent_ownership_after_handoff() -> None:
    """Reject a tool call that is owned by the wrong agent or occurs too early."""
    trace = EvalTrace(
        tool_calls=[
            ToolCall(name="rank_units", agent=AssistantName.CHAT),
            ToolCall(name="rank_units", agent=AssistantName.DATA_ANALYST),
        ],
        handoffs=[Handoff(source=AssistantName.CHAT, target=AssistantName.DATA_ANALYST)],
        events=[
            TraceEvent(type="tool_call", agent=AssistantName.CHAT, tool="rank_units"),
            TraceEvent(
                type="handoff",
                agent=AssistantName.CHAT,
                source=AssistantName.CHAT,
                target=AssistantName.DATA_ANALYST,
            ),
            TraceEvent(
                type="tool_call",
                agent=AssistantName.DATA_ANALYST,
                tool="rank_units",
            ),
        ],
    )

    assert evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "agent": AssistantName.DATA_ANALYST,
            "after_handoff": AssistantName.DATA_ANALYST,
        },
        trace,
    ).passed
    assert not evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "agent": AssistantName.CHAT,
            "after_handoff": AssistantName.DATA_ANALYST,
        },
        trace,
    ).passed


def test_tool_check_does_not_infer_order_from_aggregate_fields() -> None:
    """Require ordered events when a check claims a post-handoff tool call."""
    trace = EvalTrace(
        tool_calls=[ToolCall(name="rank_units", agent=AssistantName.DATA_ANALYST)],
        handoffs=[Handoff(source=AssistantName.CHAT, target=AssistantName.DATA_ANALYST)],
        # This intentionally places the tool before the handoff.
        events=[
            TraceEvent(type="tool_call", agent=AssistantName.DATA_ANALYST, tool="rank_units"),
            TraceEvent(
                type="handoff",
                agent=AssistantName.CHAT,
                source=AssistantName.CHAT,
                target=AssistantName.DATA_ANALYST,
            ),
        ],
    )

    result = evaluate_trace_check(
        {
            "type": "tool_called",
            "value": "rank_units",
            "agent": AssistantName.DATA_ANALYST,
            "after_handoff": AssistantName.DATA_ANALYST,
        },
        trace,
    )

    assert not result.passed


def test_extract_trace_from_sdk_like_run_result() -> None:
    run_result = _fake_run_result(
        "final",
        tool_names=("resolve_tft_names", "rank_units", "rank_units"),
        handoffs=((AssistantName.CHAT, AssistantName.DATA_ANALYST),),
        final_agent=AssistantName.DATA_ANALYST,
        turns=6,
    )

    trace = extract_trace(run_result)

    assert trace.tool_names == ["resolve_tft_names", "rank_units", "rank_units"]
    assert trace.tool_call_count("rank_units") == 2
    assert trace.handoff_targets == [AssistantName.DATA_ANALYST]
    assert trace.final_agent == AssistantName.DATA_ANALYST
    assert trace.turns == 6
    assert "rank_units x2" in trace.summary()


def test_extract_trace_pairs_tool_outputs_by_call_id() -> None:
    """Retain structured tool results for later argument-dataflow checks."""
    run_result = SimpleNamespace(
        new_items=[
            _fake_tool_call(
                "resolve_tft_names",
                '{"names":["jinx"]}',
                agent=AssistantName.CHAT,
                call_id="call-resolution",
            ),
            _fake_tool_output(
                "call-resolution",
                {"results": [{"query": "jinx", "matches": [{"name": "Jinx"}]}]},
            ),
        ]
    )

    trace = extract_trace(run_result)

    assert trace.tool_calls[0].call_id == "call-resolution"
    assert json.loads(trace.tool_calls[0].output)["results"][0]["query"] == "jinx"


def test_extract_trace_from_installed_agents_sdk_items() -> None:
    from agents import Agent
    from agents.items import HandoffOutputItem, ToolCallItem
    from openai.types.responses import ResponseFunctionToolCall

    source = Agent(name=AssistantName.CHAT, instructions="Route requests.")
    target = Agent(name=AssistantName.DATA_ANALYST, instructions="Analyze data.")
    tool_call = ToolCallItem(
        agent=target,
        raw_item=ResponseFunctionToolCall(
            arguments='{"range":[0,1]}',
            call_id="call_1",
            name="rank_units",
            type="function_call",
        ),
    )
    handoff = HandoffOutputItem(
        agent=target,
        raw_item={"type": "handoff_output"},
        source_agent=source,
        target_agent=target,
    )
    run_result = SimpleNamespace(
        new_items=[tool_call, handoff],
        last_agent=target,
        raw_responses=[object()],
    )

    trace = extract_trace(run_result)

    assert trace.tool_calls == [
        ToolCall(
            name="rank_units",
            arguments='{"range":[0,1]}',
            agent=AssistantName.DATA_ANALYST,
            call_id="call_1",
        )
    ]
    assert trace.handoffs == [Handoff(source=AssistantName.CHAT, target=AssistantName.DATA_ANALYST)]
    assert trace.final_agent == AssistantName.DATA_ANALYST
    assert trace.turns == 1
    assert trace.events == [
        TraceEvent(type="tool_call", agent=AssistantName.DATA_ANALYST, tool="rank_units"),
        TraceEvent(
            type="handoff",
            agent=AssistantName.CHAT,
            source=AssistantName.CHAT,
            target=AssistantName.DATA_ANALYST,
        ),
    ]
    assert (
        f"ordered events: {AssistantName.DATA_ANALYST} called rank_units; "
        f"{AssistantName.CHAT} -> {AssistantName.DATA_ANALYST}"
        in trace.summary()
    )


def test_extract_trace_degrades_to_empty_for_unknown_objects() -> None:
    trace = extract_trace(SimpleNamespace())

    assert trace.tool_calls == []
    assert trace.handoffs == []
    assert trace.final_agent is None


def test_trace_from_dict_accepts_string_and_object_forms() -> None:
    trace = trace_from_dict(
        {
            "tool_calls": ["rank_units", {"name": "compare_cohorts", "arguments": {"patch": "16.12"}}],
            "handoffs": [AssistantName.DATA_ANALYST, {"source": AssistantName.CHAT, "target": AssistantName.META_EXPERT}],
            "final_agent": AssistantName.META_EXPERT,
            "turns": 2,
        }
    )

    assert trace.tool_names == ["rank_units", "compare_cohorts"]
    assert trace.handoff_targets == [AssistantName.DATA_ANALYST, AssistantName.META_EXPERT]
    assert trace.final_agent == AssistantName.META_EXPERT


def test_trace_checks_pass_and_fail_on_behavior() -> None:
    trace = EvalTrace(
        tool_calls=[ToolCall(name="rank_units"), ToolCall(name="compare_cohorts")],
        handoffs=[Handoff(source=AssistantName.CHAT, target=AssistantName.DATA_ANALYST)],
        final_agent=AssistantName.DATA_ANALYST,
    )

    assert evaluate_trace_check({"type": "tool_called", "value": "rank_units"}, trace).passed
    assert not evaluate_trace_check(
        {"type": "tool_called", "value": "rank_units", "min_count": 2}, trace
    ).passed
    # values lists sum across the listed tools.
    assert evaluate_trace_check(
        {"type": "tool_called", "values": ["rank_units", "compare_cohorts"], "min_count": 2},
        trace,
    ).passed
    assert evaluate_trace_check(
        {"type": "tool_not_called", "values": ["riot_match"]}, trace
    ).passed
    assert not evaluate_trace_check(
        {"type": "tool_not_called", "value": "rank_units"}, trace
    ).passed
    assert evaluate_trace_check({"type": "handoff_to", "value": AssistantName.DATA_ANALYST}, trace).passed
    assert not evaluate_trace_check({"type": "no_handoff"}, trace).passed
    assert evaluate_trace_check({"type": "final_agent", "value": AssistantName.DATA_ANALYST}, trace).passed
    assert not evaluate_trace_check({"type": "final_agent", "value": AssistantName.CHAT}, trace).passed


def test_trace_checks_fail_gracefully_without_a_trace() -> None:
    result = evaluate_trace_check({"type": "tool_called", "value": "rank_units"}, None)

    assert not result.passed
    assert "requires an execution trace" in result.message


def test_regex_checks_search_final_output_without_a_trace() -> None:
    """Evaluate regex checks against output independently of trace capture."""

    matching = evaluate_trace_check(
        {"type": "regex", "value": r"\b812 boards\b"},
        None,
        output="The sample contains 812 boards.",
    )
    missing = evaluate_trace_check(
        {"type": "regex", "values": [r"\b900 boards\b", r"\b1,000 boards\b"]},
        None,
        output="The sample contains 812 boards.",
    )

    assert matching.passed
    assert not missing.passed


def test_resolve_eval_target_accepts_an_explicit_dsn() -> None:
    target = eval_database.resolve_eval_target("postgresql:///chat_tft")

    assert target.database == "chat_tft"
    assert target.credential_safe_url == "postgresql:///chat_tft"


def test_resolve_eval_target_changes_only_the_database_name(monkeypatch) -> None:
    base = DatabaseTarget(
        url="postgresql://eval-user@eval.example:5433/base",
        connect_url="postgresql://eval-user:secret@eval.example:5433/base",
        purpose="eval",
        auth_mode="password",
        host="eval.example",
        port=5433,
        admin="eval-user",
        database="base",
        password="secret",
    )
    monkeypatch.setattr(
        eval_database,
        "resolve_database_target",
        lambda purpose, explicit_dsn=None: base,
    )

    target = eval_database.resolve_eval_target("frozen_patch")

    assert target.database == "frozen_patch"
    assert target.credential_safe_url == (
        "postgresql://eval-user@eval.example:5433/frozen_patch"
    )
    assert target.connect_url == (
        "postgresql://eval-user:secret@eval.example:5433/frozen_patch"
    )


def test_eval_database_override_scopes_runtime_database_access() -> None:
    target = DatabaseTarget(
        url="postgresql:///eval",
        connect_url="postgresql:///eval",
        purpose="eval",
        auth_mode="maintenance_dsn",
        database="eval",
    )

    with eval_database.eval_database_override(target):
        assert resolve_runtime_database_target("app") is target


