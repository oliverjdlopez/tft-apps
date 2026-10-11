"""Contracts for portable evaluation catalogs, execution, and process isolation."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals.config import load_eval_suites
from evals import execution, worker
from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle
from evals.langfuse.contracts import legacy_execution_item
from evals.langfuse.utils import validate_case_semantics
from evals.trace import evaluate_trace_check
from evals.utils import isolated_operation

ROOT = Path(__file__).resolve().parents[1] / "evals" / "langfuse" / "snapshots"


def suite_bundle(name: str) -> dict:
    """Load a committed evaluation definition without a running platform."""
    entry = next(item for item in load_catalog(ROOT) if item["name"] == name)
    return load_snapshot(entry["snapshot"], ROOT)


def test_all_cases_and_original_assertions_are_migrated() -> None:
    """Protect the complete inventory, including the intentionally empty suite."""
    suites = load_eval_suites()
    assert {s.name: len(s.tests) for s in suites} == {
        "analyze_transcript": 0, "chat": 28, "clean_transcript": 1,
        "compact_transcript": 1, "data_analyst": 7, "dummy_assistant": 1,
        "context_selection": 11, "skill_selection": 12,
    }
    assertions = [a for s in suites for t in s.tests if t.get("metadata", {}).get("scoring") != "none" for a in t.get("metadata", {}).get("legacy_definition", t)["expected_output"]["assertions"]]
    assert sum(a["kind"] == "rubric" for a in assertions) == 15
    assert sum(a["kind"] == "trace" for a in assertions) == 64


def test_preflight_rejects_invalid_suite_routing() -> None:
    """Reject cases pointing outside their parent suite before execution."""
    bundle = suite_bundle("chat")
    bundle["items"][0]["id"] = "wrong/case"
    with pytest.raises(ValueError, match="within their suite"):
        validate_bundle(bundle)


def test_preflight_rejects_stale_tool_and_malformed_regex() -> None:
    """Preserve graph reachability and Python regex validation."""
    for check, message in [({"type": "tool_called", "value": "removed_tool"}, "unavailable tool"),
                           ({"type": "regex", "value": "["}, "invalid regex")]:
        bundle = suite_bundle("chat")
        item = next(item for item in bundle["items"] if item.get("metadata", {}).get("scoring") != "none")
        if bundle['schema_version'] in {2, 3}:
            item['metadata']['deterministic_checks'] = [{"kind": "trace", "name": "check", "check": check}]
        else:
            item["expected_output"]["assertions"] = [{"kind": "trace", "name": "check", "check": check}]
        with pytest.raises(ValueError, match=message):
            validate_bundle(bundle)
            validate_case_semantics(bundle["suite"], bundle["items"])


def test_fixture_and_trace_assertions_do_not_need_credentials(monkeypatch) -> None:
    """The fixture bypasses model clients, database access, and worker processes."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    bundle = suite_bundle("dummy_assistant")
    item = bundle["items"][0]
    response = execution.execute_attempt(bundle["suite"], item, {}, bundle["prompts"])
    scores = execution.score_attempt(item, response, bundle["prompts"])
    assert all(score["passed"] for score in scores)
    assert response["metadata"]["execution"] == "fixture"


def test_live_execution_uses_neutral_worker_protocol(monkeypatch) -> None:
    """An isolated operation receives frozen input without launcher-owned locks."""
    calls = []
    def operation(payload, timeout):
        """Capture the execution boundary without calling a model or database."""
        calls.append((payload, timeout))
        return {"output": "native call"}
    monkeypatch.setattr(execution, "isolated_operation", operation)
    bundle = suite_bundle("chat")
    item = bundle["items"][0]
    from evals.langfuse.assistant_workspace import current_execution
    variants = bundle["config"]["variants"]
    captured = current_execution(bundle["suite"], variants)
    suite = {**bundle["suite"], "captured_graphs": captured["graphs"]}
    result = execution.execute_attempt(suite, item, variants[0], bundle["prompts"])
    assert result["output"] == "native call"
    assert calls[0][0]["input"] == legacy_execution_item(item)["input"]
    assert calls[0][0]["operation"] == "evaluate"
    assert calls[0][1] > 0


def test_timeout_terminates_isolated_worker() -> None:
    """A timed-out operation returns promptly instead of leaving daemon work."""
    with pytest.raises(TimeoutError, match="exceeded"):
        isolated_operation({"operation": "evaluate", "config": {"family": "context_selection"},
                            "input": {"input": "request"}}, 0.001)


def test_assistant_execution_uses_real_assembly_and_scoped_target(monkeypatch) -> None:
    """Model and prompt candidates reach the registry without editing specs."""
    import agents
    import agents.tracing
    import domain.assistants as assistants
    calls = {}

    @contextmanager
    def database_scope(target):
        """Record target scope during the fake SDK execution."""
        calls["target"] = target
        calls["in_scope"] = True
        yield
        calls["in_scope"] = False

    @contextmanager
    def trace_scope(*args, **kwargs):
        """Supply a deterministic trace ID without contacting the dashboard."""
        yield SimpleNamespace(trace_id="trace_test")

    from evals import assistant_execution

    def run(prompt, config):
        """Stand in for a prepared invocation while observing database ownership."""
        assert calls['in_scope']
        calls['config'] = config
        result = SimpleNamespace(final_output='answer', new_items=[], last_agent=SimpleNamespace(name='chat'),
            context_wrapper=SimpleNamespace(usage=SimpleNamespace(input_tokens=10, output_tokens=2, total_tokens=12, requests=1)))
        return result, {'instruction_hashes': {'chat': 'hash'}}

    monkeypatch.setattr(worker, 'resolve_eval_target', lambda _, **kwargs: SimpleNamespace(database='eval-snapshot'))
    monkeypatch.setattr(worker, 'eval_database_override', database_scope)
    monkeypatch.setattr(assistant_execution, 'require_capture', lambda config: None)
    monkeypatch.setattr(assistant_execution, 'run_captured', run)
    monkeypatch.setattr(agents.tracing, 'trace', trace_scope)
    response = worker.run_assistant('question', {'assistant': 'chat', 'captured_graph': {}, 'model': 'candidate',
        'prompt_candidates': {'chat': {'text': 'new instructions'}}, 'max_turns': 7}, {})
    assert response['output'] == 'answer'
    assert response['metadata']['tft_trace']['trace_id'] == 'trace_test'
    assert response['metadata']['instructions_sha256'] == 'hash'
    assert calls['config']['max_turns'] == 7
    assert not calls['in_scope']


@pytest.mark.parametrize("output", ["5%", "five percent", "1 in 20", "0.05"])
def test_probability_case_keeps_python_regex_contract(output) -> None:
    """Equivalent probability forms retain their existing case semantics."""
    case = next(t for t in suite_bundle("chat")["items"] if t["metadata"]["case"] == "context_six_anima_thiefs_gloves_odds")
    assertion = next(a for a in legacy_execution_item(case)["expected_output"]["assertions"] if a.get("check", {}).get("type") == "regex")
    assert evaluate_trace_check(assertion["check"], None, output).passed
    assert not evaluate_trace_check(assertion["check"], None, "0.5% and 15%").passed
