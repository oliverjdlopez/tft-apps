"""Implementation helpers shared by evaluation execution and assertions."""
from __future__ import annotations
import json
import re
import os
from collections.abc import Mapping
from typing import Any
from .models import EvalTrace, ToolCall, Handoff, TraceEvent

DEFAULT_EVAL_OPERATION_TIMEOUT_SECONDS = 180.0
EVAL_OPERATION_TIMEOUT_ENV = "EVAL_OPERATION_TIMEOUT_SECONDS"

# ======================================================================
# Execution database selection
#
# Case metadata selects a database without carrying connection credentials.
# Validation is shared by snapshot ingestion and isolated attempt dispatch.
# ======================================================================

def evaluation_database(suite: Mapping[str, Any], item: Mapping[str, Any]) -> str | None:
    """Select a case database, falling back to suite and typed eval defaults.

    Args:
        suite: Execution defaults, including an optional database name.
        item: Dataset case whose metadata may override the database name.

    Returns:
        Database name, or None to use the configured RDS_EVAL target.

    Raises:
        ValueError: A database value is not a plain, nonempty database name.
    """
    case_database = item.get("metadata", {}).get("database")
    # Validate both levels so a case override cannot conceal malformed defaults.
    for value in (suite.get("database"), case_database):
        if value is not None and (
            not isinstance(value, str) or not value.strip() or value != value.strip()
            or "://" in value or "=" in value or any(char in value for char in "\x00\r\n")
        ):
            raise ValueError("Evaluation database must be a plain database name, not a connection string")
    return case_database if case_database is not None else suite.get("database")

# ======================================================================
# Trace assertions and extraction
#
# Preserve the established ordering and resolver provenance contracts.
# These helpers are shared by trace.py and execution evidence rendering.
# ======================================================================

def json_value_contains(actual: Any, expected: Any) -> bool:
    """Check whether a JSON value contains an expected JSON subset.

    Mapping values are matched recursively so manifests can assert only the
    meaningful arguments of a strict tool call while ignoring explicit
    defaults. Lists and scalar values remain exact to protect bounded tool
    schemas from shape changes such as a scalar condition becoming a list.

    Args:
        actual: Parsed JSON value captured from a tool call.
        expected: Parsed JSON subset declared by an eval check.

    Returns:
        Whether every expected value is present with the same JSON shape.
    """
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return False
        return all(
            key in actual and json_value_contains(actual[key], value)
            for key, value in expected.items()
        )
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return actual == expected

def tool_arguments_contain(
    arguments: str, expected: Mapping[str, Any]
) -> bool:
    """Match captured tool arguments against a manifest argument subset.

    Args:
        arguments: Raw JSON argument text captured from the Agents SDK.
        expected: Non-empty argument subset declared by the eval manifest.

    Returns:
        Whether the captured arguments are a JSON object containing the subset.
    """
    try:
        actual = json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return False
    return isinstance(actual, Mapping) and json_value_contains(actual, expected)

def resolve_eval_operation_timeout(value: float | None = None) -> float:
    """Resolve the maximum duration of one blocking eval operation.

    Args:
        value: Explicit timeout override in seconds. When omitted, the
            ``EVAL_OPERATION_TIMEOUT_SECONDS`` environment variable is used.

    Returns:
        A positive timeout in seconds.

    Raises:
        ValueError: If the configured timeout is not positive and finite.
    """
    raw: float | str = value if value is not None else os.environ.get(
        EVAL_OPERATION_TIMEOUT_ENV,
        str(DEFAULT_EVAL_OPERATION_TIMEOUT_SECONDS),
    )
    try:
        resolved = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{EVAL_OPERATION_TIMEOUT_ENV} must be a positive number, got {raw!r}"
        ) from exc
    if resolved <= 0 or resolved == float("inf") or resolved != resolved:
        raise ValueError(
            f"{EVAL_OPERATION_TIMEOUT_ENV} must be a positive number, got {raw!r}"
        )
    return resolved

def _evaluate_regex_check(
    config: Mapping[str, Any], output: str | None
) -> tuple[float, str]:
    """Search final output for any configured regular-expression pattern."""

    patterns = _expected_names(config)
    compiled_patterns: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled_patterns.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"invalid regex pattern {pattern!r}: {exc}") from exc

    matched_pattern = next(
        (
            pattern.pattern
            for pattern in compiled_patterns
            if output is not None and pattern.search(output)
        ),
        None,
    )
    expected = " or ".join(repr(pattern) for pattern in patterns)
    matched = repr(matched_pattern) if matched_pattern is not None else "none"
    return (
        float(matched_pattern is not None),
        f"expected output to match {expected}; matched: {matched}",
    )


def _evaluate_check(
    trace: EvalTrace, check_type: str, config: Mapping[str, Any]
) -> tuple[float, str]:
    """Evaluate a known check type. Config validation happens as it is read."""

    if check_type == "tool_called":
        names = _expected_names(config)
        agent = _optional_agent(config)
        after_handoff = config.get("after_handoff")
        if after_handoff is not None and not isinstance(after_handoff, str):
            raise ValueError("check after_handoff must be a non-empty string")
        if isinstance(after_handoff, str) and not after_handoff:
            raise ValueError("check after_handoff must be a non-empty string")
        expected_arguments = config.get("arguments")
        if expected_arguments is not None and (
            not isinstance(expected_arguments, Mapping) or not expected_arguments
        ):
            raise ValueError("tool_called arguments must be a non-empty object")
        if expected_arguments is not None and after_handoff is not None:
            raise ValueError(
                "tool_called arguments cannot be combined with after_handoff"
            )
        min_count = config.get("min_count", 1)
        if (
            not isinstance(min_count, int)
            or isinstance(min_count, bool)
            or min_count < 1
        ):
            raise ValueError("tool_called min_count must be a positive integer")
        if after_handoff is None:
            total = sum(
                1
                for call in trace.tool_calls
                if call.name in names and (agent is None or call.agent == agent)
                and (
                    expected_arguments is None
                    or tool_arguments_contain(call.arguments, expected_arguments)
                )
            )
        else:
            total = sum(
                1
                for index, event in enumerate(trace.events)
                if event.type == "tool_call"
                and event.tool in names
                and (agent is None or event.agent == agent)
                and any(
                    prior.type == "handoff" and prior.target == after_handoff
                    for prior in trace.events[:index]
                )
            )
        expected = " or ".join(repr(name) for name in names)
        scope = ""
        if agent is not None:
            scope = f" by {agent!r}"
        if after_handoff is not None:
            scope += f" after handoff to {after_handoff!r}"
        if expected_arguments is not None:
            scope += " with arguments containing " + json.dumps(
                expected_arguments, sort_keys=True
            )
        return (
            float(total >= min_count),
            f"expected at least {min_count} call(s) to {expected}{scope}; "
            f"trace tools: {trace.tool_names or 'none'}",
        )

    if check_type == "tool_argument_resolved":
        return _evaluate_resolved_argument_check(trace, config)

    if check_type == "tool_not_called":
        names = _expected_names(config)
        called = [name for name in names if trace.tool_call_count(name)]
        return (
            float(not called),
            f"expected {', '.join(names)} not to be called; "
            f"trace tools: {trace.tool_names or 'none'}",
        )

    if check_type == "handoff_to":
        names = _expected_names(config)
        matched = any(target in names for target in trace.handoff_targets)
        return (
            float(matched),
            f"expected handoff to {' or '.join(names)}; "
            f"trace handoffs: {trace.handoff_targets or 'none'}",
        )

    if check_type == "no_handoff":
        return (
            float(not trace.handoffs),
            f"expected no handoffs; trace handoffs: {trace.handoff_targets or 'none'}",
        )

    names = _expected_names(config)  # final_agent
    return (
        float(trace.final_agent in names),
        f"expected final agent {' or '.join(names)}; "
        f"trace final agent: {trace.final_agent or 'unknown'}",
    )


def _evaluate_resolved_argument_check(
    trace: EvalTrace, config: Mapping[str, Any]
) -> tuple[float, str]:
    """Verify that a later tool argument came from stored-name resolution.

    Args:
        trace: Ordered tool calls captured from one assistant run.
        config: Manifest check declaring the target tool, query, and argument.

    Returns:
        Binary score and a diagnostic description of the dataflow check.
    """
    target_names = _expected_names(config)
    agent = _optional_agent(config)
    query = config.get("query")
    if not isinstance(query, str) or not query:
        raise ValueError("tool_argument_resolved query must be a non-empty string")
    argument_fields = _resolved_argument_fields(config.get("argument"))
    expected_arguments = config.get("arguments")
    if expected_arguments is not None and (
        not isinstance(expected_arguments, Mapping) or not expected_arguments
    ):
        raise ValueError(
            "tool_argument_resolved arguments must be a non-empty object"
        )
    if config.get("after_handoff") is not None:
        raise ValueError(
            "tool_argument_resolved cannot be combined with after_handoff"
        )

    query_key = query.casefold()
    resolution_candidates: list[tuple[int, set[str]]] = []
    for index, call in enumerate(trace.tool_calls):
        if call.name != "resolve_tft_names" or (
            agent is not None and call.agent != agent
        ):
            continue
        source_arguments = _json_object(call.arguments)
        submitted_names = source_arguments.get("names") if source_arguments else None
        if not isinstance(submitted_names, list) or not any(
            isinstance(name, str) and name.casefold() == query_key
            for name in submitted_names
        ):
            continue
        candidates = _resolution_candidate_names(call.output, query_key)
        if candidates:
            resolution_candidates.append((index, candidates))

    for source_index, candidates in resolution_candidates:
        for call in trace.tool_calls[source_index + 1 :]:
            if call.name not in target_names or (
                agent is not None and call.agent != agent
            ):
                continue
            target_arguments = _json_object(call.arguments)
            if target_arguments is None:
                continue
            if expected_arguments is not None and not tool_arguments_contain(
                call.arguments, expected_arguments
            ):
                continue
            if any(
                target_arguments.get(field) in candidates
                for field in argument_fields
            ):
                return (
                    1.0,
                    f"resolved {query!r} to a candidate passed as "
                    f"{', '.join(argument_fields)} to {call.name!r}",
                )

    expected = " or ".join(repr(name) for name in target_names)
    return (
        0.0,
        f"expected {query!r} to be resolved before {expected} and one of "
        f"{', '.join(argument_fields)} to equal a returned candidate",
    )


def _resolved_argument_fields(value: Any) -> list[str]:
    """Validate the downstream argument field or fields in a dataflow check.

    Args:
        value: Manifest ``argument`` value.

    Returns:
        One or more non-empty target argument names.
    """
    if isinstance(value, str) and value:
        return [value]
    if (
        isinstance(value, list)
        and value
        and all(isinstance(field, str) and field for field in value)
    ):
        return value
    raise ValueError(
        "tool_argument_resolved argument must be a non-empty string or list of strings"
    )


def _json_object(value: str) -> Mapping[str, Any] | None:
    """Parse one captured JSON string when it contains an object.

    Args:
        value: Serialized tool arguments or output.

    Returns:
        Parsed mapping, or ``None`` for invalid JSON and non-object values.
    """
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _resolution_candidate_names(output: str, query_key: str) -> set[str]:
    """Extract exact candidate names for one query from a resolution result.

    Args:
        output: Serialized ``resolve_tft_names`` result.
        query_key: Case-folded query declared by the manifest check.

    Returns:
        Exact stored candidate names returned for that query.
    """
    payload = _json_object(output)
    results = payload.get("results") if payload else None
    if not isinstance(results, list):
        return set()
    candidates: set[str] = set()
    for entry in results:
        if not isinstance(entry, Mapping):
            continue
        entry_query = entry.get("query")
        if not isinstance(entry_query, str) or entry_query.casefold() != query_key:
            continue
        matches = entry.get("matches")
        if not isinstance(matches, list):
            continue
        candidates.update(
            name
            for match in matches
            if isinstance(match, Mapping)
            and isinstance((name := match.get("name")), str)
            and name
        )
    return candidates


def _events_from_manifest(
    payload: Mapping[str, Any],
    tool_calls: list[ToolCall],
    handoffs: list[Handoff],
) -> list[TraceEvent]:
    """Build ordered fixture events, retaining legacy trace payload support."""
    raw_events = payload.get("events")
    if isinstance(raw_events, list):
        events: list[TraceEvent] = []
        for raw_event in raw_events:
            if not isinstance(raw_event, Mapping):
                continue
            event_type = str(raw_event.get("type") or "")
            if event_type == "tool_call" and raw_event.get("tool"):
                events.append(
                    TraceEvent(
                        type=event_type,
                        agent=_optional_manifest_string(raw_event.get("agent")),
                        tool=str(raw_event["tool"]),
                    )
                )
            elif (
                event_type == "handoff"
                and raw_event.get("source")
                and raw_event.get("target")
            ):
                events.append(
                    TraceEvent(
                        type=event_type,
                        agent=str(raw_event["source"]),
                        source=str(raw_event["source"]),
                        target=str(raw_event["target"]),
                    )
                )
        return events

    # Legacy fixtures did not preserve interleaving, so retain their aggregate
    # checks while making new fixtures opt into exact event ordering explicitly.
    return [
        *[
            TraceEvent(type="tool_call", agent=call.agent, tool=call.name)
            for call in tool_calls
        ],
        *[
            TraceEvent(
                type="handoff",
                agent=handoff.source or None,
                source=handoff.source or None,
                target=handoff.target,
            )
            for handoff in handoffs
        ],
    ]


def _optional_manifest_string(value: Any) -> str | None:
    """Normalize an optional manifest string without inventing ownership."""
    return None if value is None else str(value)


def _optional_agent(config: Mapping[str, Any]) -> str | None:
    """Read an optional agent scope from a trace check."""
    value = config.get("agent")
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("check agent must be a non-empty string")
    return value


def _event_summary(event: TraceEvent) -> str:
    """Render one ordered event for judge prompts and human reports."""
    if event.type == "handoff":
        return f"{event.source or '?'} -> {event.target or '?'}"
    if event.type == "tool_call":
        return f"{event.agent or '?'} called {event.tool or '?'}"
    return event.type


def _item_arguments(item: Any) -> str:
    """Extract serialized arguments from SDK items during trace normalization."""
    raw = getattr(item, "raw_item", None)
    arguments = raw.get("arguments") if isinstance(raw, dict) else getattr(raw, "arguments", None)
    return _as_arguments(arguments)


def _item_call_id(item: Any) -> str | None:
    """Read an SDK tool call identity from a call or output item.

    Args:
        item: Agents SDK run item or an SDK-shaped test double.

    Returns:
        Stable call identifier when the item exposes one.
    """
    call_id = getattr(item, "call_id", None)
    if call_id is not None:
        return str(call_id)
    raw = getattr(item, "raw_item", None)
    if isinstance(raw, Mapping):
        value = raw.get("call_id") or raw.get("id")
    else:
        value = getattr(raw, "call_id", None) or getattr(raw, "id", None)
    return None if value is None else str(value)


def _as_arguments(arguments: Any) -> str:
    """Normalize string and object arguments to one JSON trace representation."""
    if arguments is None:
        return ""
    if isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(arguments)


def _agent_name(agent: Any) -> str | None:
    """Resolve an optional SDK agent label for trace ownership checks."""
    if agent is None:
        return None
    name = getattr(agent, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _expected_names(config: Mapping[str, Any]) -> list[str]:
    """Validate one or more expected names used by deterministic assertions."""
    values = config.get("values")
    if values is not None:
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
        ):
            raise ValueError("check values must be a non-empty list of strings")
        return values
    value = config.get("value")
    if not isinstance(value, str) or not value:
        raise ValueError("check value must be a non-empty string")
    return [value]


def _number(value: Any, label: str) -> float:
    """Validate a numeric assertion setting before scoring."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise ValueError(f"check {label} must be numeric")
    return float(value)



# ======================================================================
# Evaluation process boundary
#
# The experiment service schedules assistant operations and rubric graders.
# Isolating each operation lets a timeout actually stop its local work.
# ======================================================================

from pathlib import Path
import signal
import subprocess
import sys


def isolated_operation(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Execute an SDK operation in a killable process with a JSON protocol.

    Args:
        payload: Operation, configuration, input, and identity; never shell-interpolated.
        timeout: Maximum operation duration in seconds, including SDK setup.

    Returns:
        Execution output and metadata, or raises for process/transport failures.
    """
    worker_environment = os.environ.copy()
    if payload.get('config', {}).get('workspace_trial'):
        payload = {**payload, 'parent_pid': os.getpid()}
    if payload.get('operation') == 'evaluate' and not payload.get('config', {}).get('workspace_trial'):
        try:
            from opentelemetry import propagate, trace
            if trace.get_current_span().get_span_context().is_valid:
                carrier = {}
                propagate.inject(carrier)
                payload = {**payload, 'trace_context': carrier}
                from dotenv import dotenv_values
                local = dotenv_values(Path(__file__).parent / 'langfuse' / '.env')
                for key in ('LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY'):
                    if key not in worker_environment and local.get(key):
                        worker_environment[key] = local[key]
                worker_environment.setdefault('LANGFUSE_BASE_URL', 'http://localhost:15510')
        except ImportError:
            pass
    process = subprocess.Popen(
        [sys.executable, "-m", "evals.worker"],
        cwd=Path(__file__).resolve().parents[1],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, start_new_session=True, env=worker_environment,
    )
    try:
        output, _ = process.communicate(json.dumps(payload), timeout=timeout)
        if process.returncode:
            raise RuntimeError(f"Eval worker exited with status {process.returncode}")
        return json.loads(output)
    except subprocess.TimeoutExpired as exc:
        # Give the worker a bounded opportunity to flush completed telemetry;
        # the finalizer still kills every remaining process in the operation group.
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.communicate(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass
        raise TimeoutError(f"Eval operation exceeded {timeout:g} seconds") from exc
    finally:
        # Kill the whole operation group, including any still-running children.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()

# ======================================================================
# Native configuration validation
#
# Registry reachability prevents obsolete tools from silently becoming
# permanent live-eval failures. No models or databases are invoked here.
# ======================================================================

def validate_registry_references(assistant: str, cases: list[dict[str, Any]]) -> None:
    """Check positive assertions against the current registered assistant graph."""
    from domain.assistants import (
        assistant_handoff_names,
        assistant_reachable_tool_names,
        assistant_spec,
    )

    try:
        assistant_spec(assistant)
    except KeyError:
        raise ValueError(f"live eval targets unknown assistant {assistant!r}") from None

    reachable_assistants = {assistant}
    handoff_targets: set[str] = set()
    pending = [assistant]
    while pending:
        current = pending.pop()
        for target in assistant_handoff_names(current):
            handoff_targets.add(target)
            if target not in reachable_assistants:
                reachable_assistants.add(target)
                pending.append(target)

    reachable_tools = set(assistant_reachable_tool_names(assistant))
    for case in cases:
        for check in [a["check"] for a in case["expected_output"]["assertions"] if a["kind"] == "trace"]:
            check_type = str(check["type"])
            if check_type not in {
                "tool_called",
                "tool_argument_resolved",
                "handoff_to",
                "final_agent",
            }:
                continue
            expected = _expected_names(check)
            available = (
                reachable_tools
                if check_type in {"tool_called", "tool_argument_resolved"}
                else handoff_targets
                if check_type == "handoff_to"
                else reachable_assistants
            )
            unavailable = sorted(set(expected) - available)
            if unavailable:
                noun = {
                    "tool_called": "unavailable tool",
                    "tool_argument_resolved": "unavailable tool",
                    "handoff_to": "unreachable handoff target",
                    "final_agent": "unreachable final agent",
                }[check_type]
                raise ValueError(
                    f"case {case['metadata']['case']!r} expects {noun}(s): {', '.join(unavailable)}"
                )

            if check_type not in {"tool_called", "tool_argument_resolved"}:
                continue
            agent = check.get("agent")
            if agent is not None and agent not in reachable_assistants:
                raise ValueError(
                    f"case {case['metadata']['case']!r} expects unavailable tool owner: {agent}"
                )
            after_handoff = check.get("after_handoff")
            if after_handoff is not None and after_handoff not in handoff_targets:
                raise ValueError(
                    f"case {case['metadata']['case']!r} expects unreachable handoff target: "
                    f"{after_handoff}"
                )
            if (
                check_type == "tool_argument_resolved"
                and "resolve_tft_names" not in reachable_tools
            ):
                raise ValueError(
                    f"case {case['metadata']['case']!r} requires unavailable resolution tool: "
                    "resolve_tft_names"
                )


def selector_case(input_data: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Combine frozen selector input with canonical expectations and case identity.

    Args:
        input_data: Input text and selector expectations from the frozen item.
        identity: Stable case metadata.

    Returns:
        The one-attempt selector contract, without duplicate query/name fields.
    """
    return {**input_data["expected"], "name": identity["case"], "query": input_data["input"]}

# ======================================================================
# Neutral execution and scoring
#
# Shared semantics stay independent of platform response envelopes.
# Frozen text templates preserve the same request/trace grading evidence.
# ======================================================================


def selector_score(selector: str, metrics: dict[str, Any]) -> float:
    """Return one selector metric using the established offline/live policy."""
    selected = metrics.get("live_result", metrics)
    required = metrics["required_count"]
    hits = selected.get("required_hits", metrics.get("final_required_hits", 0))
    forbidden = selected.get("forbidden_hits", metrics.get("final_forbidden_hits", 0))
    recall = hits / required if required else 1.0
    return float({
        "offline_selection_policy": float(metrics["offline_passed"]),
        "shortlist_required_recall": metrics.get("shortlist_required_hits", 0) / required if required else 1.0,
        "final_required_recall": recall,
        "required_skill_recall": recall,
        "forbidden_context_excluded": float(forbidden == 0),
        "forbidden_skills_excluded": float(forbidden == 0),
        "payload_reduction": metrics.get("payload_reduction", 0.0),
        "selection_policy": float(metrics.get("live_passed", metrics["offline_passed"])),
    }[selector])


def render_judge_prompt(template: str, item: dict, result: dict, rubric: str) -> str:
    """Substitute frozen rubric variables once without interpreting user text."""
    evidence = json.dumps({"request": item["input"]["input"],
                           "intent": item.get("metadata", {}).get("description", ""),
                           "trace": result.get("metadata", {}).get("trace_summary", ""),
                           "answer": result.get("output", "")}, ensure_ascii=False)
    values = {"rubric": rubric, "output": evidence, "input": item["input"]["input"]}
    return re.sub(r"{{\s*(rubric|output|input)\s*}}", lambda match: values[match.group(1)], template)


def eval_graph_instructions(name: str, prompt: str, candidates: dict) -> dict[str, str]:
    """Assemble each reachable assistant's frozen base with its own context policy."""
    from domain.assistants import assistant_handoff_names, build_assistant_instructions
    instructions = {}
    pending = [name]
    while pending:
        current = pending.pop()
        if current in instructions:
            continue
        candidate = candidates.get(current)
        instructions[current] = build_assistant_instructions(
            current, prompt, base_instructions=candidate["text"] if candidate else None)
        pending.extend(assistant_handoff_names(current))
    return instructions



def frozen_langfuse_prompt(prompt: dict[str, Any] | None) -> Any:
    """Reconstruct an SDK prompt reference from frozen text without fetching edits."""
    if prompt is None or ("native_reference" in prompt and prompt["native_reference"] is None):
        return None
    reference = prompt.get("native_reference") or prompt
    from langfuse.api import Prompt_Text
    from langfuse.model import TextPromptClient
    return TextPromptClient(Prompt_Text(
        name=reference["name"], version=reference["version"], prompt=prompt["text"],
        config={}, labels=[], tags=[], resolution_graph=prompt.get("resolution_graph")))



def experiment_item_report(row: Any) -> dict[str, Any]:
    """Serialize SDK item results so ephemeral CI retains scores and execution evidence."""
    item = row.item
    metadata = item.get("metadata", {}) if isinstance(item, dict) else item.metadata or {}
    case_id = metadata.get("case_id") or f"{metadata.get('suite', '')}/{metadata.get('case', '')}"
    scores = [{"name": score.name, "value": score.value, "comment": score.comment,
               **(score.metadata or {})} for score in row.evaluations]
    return {"id": case_id, "remote_id": getattr(item, "id", None), "result": row.output,
            "scores": scores, "trace_id": row.trace_id, "dataset_run_id": row.dataset_run_id}



def public_experiment_url(url: str | None) -> str | None:
    """Translate internal SDK result links to the browser-accessible Langfuse origin."""
    if not url:
        return None
    from urllib.parse import urlsplit, urlunsplit
    public = urlsplit(os.environ.get("LANGFUSE_PUBLIC_URL", "http://localhost:15510"))
    internal = urlsplit(url)
    return urlunsplit((public.scheme, public.netloc, public.path.rstrip("/") + internal.path,
                       internal.query, internal.fragment))



def prompt_reference_key(prompt: dict[str, Any]) -> str:
    """Identify frozen prompt content independently of destination version numbers."""
    import hashlib
    return f"{prompt['name']}@{prompt['version']}:{hashlib.sha256(prompt['text'].encode()).hexdigest()}"


def execution_evidence(result: dict) -> dict:
    """Bound judge evidence while leaving full tool payloads in observations."""
    trace = result.get('metadata', {}).get('tft_trace') or {}
    presentations = [event for event in trace.get('events', [])
                     if event.get('name') in {'present_evidence', 'present_inline_data'}]
    return {'trace_summary': result.get('metadata', {}).get('trace_summary', '')[:12000],
            'presentation': json.dumps(presentations, ensure_ascii=False)[:12000]}
