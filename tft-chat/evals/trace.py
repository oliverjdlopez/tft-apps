"""Capture SDK behavior and apply deterministic domain assertions."""
from __future__ import annotations
import json
from dataclasses import replace
from collections.abc import Mapping
from typing import Any
from .models import EvalTrace, ToolCall, Handoff, TraceEvent, TraceCheckResult
from .utils import (_evaluate_regex_check, _evaluate_check, _evaluate_resolved_argument_check, _resolved_argument_fields, _json_object, _resolution_candidate_names, _events_from_manifest, _optional_manifest_string, _optional_agent, _event_summary, _item_arguments, _item_call_id, _as_arguments, _agent_name, _expected_names, _number)

TRACE_CHECK_TYPES = frozenset(
    {
        "tool_called",
        "tool_argument_resolved",
        "tool_not_called",
        "handoff_to",
        "no_handoff",
        "final_agent",
        "regex",
    }
)

def evaluate_trace_check(
    config: Mapping[str, Any],
    trace: EvalTrace | None,
    output: str | None = None,
) -> TraceCheckResult:
    """Evaluate one manifest check against the output or execution trace."""

    check_type = str(config.get("type") or "")
    if check_type not in TRACE_CHECK_TYPES:
        raise ValueError(f"unsupported trace check {check_type!r}")

    name = str(config.get("name") or check_type)
    threshold = _number(config.get("threshold", 1.0), "threshold")
    weight = _number(config.get("weight", 1.0), "weight")
    if not 0 <= threshold <= 1:
        raise ValueError(f"check {name!r} threshold must be between 0 and 1")
    if weight <= 0:
        raise ValueError(f"check {name!r} weight must be greater than zero")

    if check_type == "regex":
        score, message = _evaluate_regex_check(config, output)
    elif trace is None:
        score = 0.0
        message = "check requires an execution trace, but none was captured"
    else:
        score, message = _evaluate_check(trace, check_type, config)

    return TraceCheckResult(
        name=name,
        check_type=check_type,
        score=score,
        threshold=threshold,
        passed=score >= threshold,
        weight=weight,
        message=message,
    )


def extract_trace(run_result: Any, *, trace_id: str | None = None) -> EvalTrace:
    """Build an :class:`EvalTrace` from an ``agents`` SDK ``RunResult``.

    Every field access is defensive so test doubles and future SDK versions
    degrade to an empty trace instead of raising.
    """
    tool_calls: list[ToolCall] = []
    output_by_call_id: dict[str, str] = {}
    handoffs: list[Handoff] = []
    events: list[TraceEvent] = []
    for item in getattr(run_result, "new_items", None) or []:
        item_type = getattr(item, "type", "")
        if item_type == "tool_call_item":
            name = getattr(item, "tool_name", None)
            if name is None:
                raw = getattr(item, "raw_item", None)
                name = raw.get("name") if isinstance(raw, dict) else getattr(raw, "name", None)
            if name:
                tool_name = str(name)
                agent = _agent_name(getattr(item, "agent", None))
                tool_calls.append(
                    ToolCall(
                        name=tool_name,
                        arguments=_item_arguments(item),
                        agent=agent,
                        call_id=_item_call_id(item),
                    )
                )
                events.append(
                    TraceEvent(type="tool_call", agent=agent, tool=tool_name)
                )
        elif item_type == "tool_call_output_item":
            call_id = _item_call_id(item)
            if call_id is not None:
                output_by_call_id[call_id] = _as_arguments(
                    getattr(item, "output", None)
                )
        elif item_type == "handoff_output_item":
            source = _agent_name(getattr(item, "source_agent", None))
            target = _agent_name(getattr(item, "target_agent", None))
            if target:
                handoffs.append(Handoff(source=source or "", target=target))
                events.append(
                    TraceEvent(
                        type="handoff",
                        agent=source,
                        source=source,
                        target=target,
                    )
                )

    final_agent = _agent_name(getattr(run_result, "last_agent", None))
    raw_responses = getattr(run_result, "raw_responses", None)
    turns = len(raw_responses) if isinstance(raw_responses, list) else None
    resolved_tool_calls = [
        replace(
            call,
            output=(
                output_by_call_id.get(call.call_id, "")
                if call.name == "resolve_tft_names"
                else ""
            ),
        )
        for call in tool_calls
    ]
    return EvalTrace(
        trace_id=trace_id,
        tool_calls=resolved_tool_calls,
        handoffs=handoffs,
        final_agent=final_agent,
        turns=turns,
        events=events,
    )


def trace_from_dict(payload: Mapping[str, Any]) -> EvalTrace:
    """Build a trace from a manifest dict (fixture cases and tests)."""
    tool_calls: list[ToolCall] = []
    for raw_call in payload.get("tool_calls", []) or []:
        if isinstance(raw_call, str):
            tool_calls.append(ToolCall(name=raw_call))
        elif isinstance(raw_call, Mapping) and raw_call.get("name"):
            tool_calls.append(
                ToolCall(
                    name=str(raw_call["name"]),
                    arguments=_as_arguments(raw_call.get("arguments")),
                    agent=(
                        None
                        if raw_call.get("agent") is None
                        else str(raw_call["agent"])
                    ),
                    call_id=_optional_manifest_string(raw_call.get("call_id")),
                    output=_as_arguments(raw_call.get("output")),
                )
            )
    handoffs: list[Handoff] = []
    for raw_handoff in payload.get("handoffs", []) or []:
        if isinstance(raw_handoff, str):
            handoffs.append(Handoff(source="", target=raw_handoff))
        elif isinstance(raw_handoff, Mapping) and raw_handoff.get("target"):
            handoffs.append(
                Handoff(
                    source=str(raw_handoff.get("source") or ""),
                    target=str(raw_handoff["target"]),
                )
            )
    final_agent = payload.get("final_agent")
    turns = payload.get("turns")
    return EvalTrace(
        tool_calls=tool_calls,
        handoffs=handoffs,
        final_agent=None if final_agent is None else str(final_agent),
        turns=None if turns is None else int(turns),
        events=_events_from_manifest(payload, tool_calls, handoffs),
    )


