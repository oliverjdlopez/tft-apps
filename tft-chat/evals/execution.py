"""Execute and score frozen evaluation cases independently of a platform."""
from __future__ import annotations

import json
import math
import time
from typing import Any

from evals.trace import evaluate_trace_check, trace_from_dict
from evals.utils import evaluation_database, isolated_operation, resolve_eval_operation_timeout, selector_score, render_judge_prompt


def execute_attempt(suite: dict, item: dict, variant: dict, prompts: dict) -> dict[str, Any]:
    """Run one case with frozen prompt candidates and a killable SDK boundary.

    Args:
        suite: Platform-independent execution and database settings.
        item: Frozen input, expectations, and stable case identity.
        variant: Model and already-resolved prompt candidate combination.
        prompts: Frozen baseline prompt definitions.

    Returns:
        Output, trace evidence, usage, latency, and any execution error.
    """
    from evals.langfuse.contracts import legacy_execution_item
    item = legacy_execution_item(item)
    started = time.perf_counter()
    try:
        database = evaluation_database(suite, item)
        if suite.get("execution") == "fixture":
            fixture = item["input"]["fixture"]
            captured = trace_from_dict(fixture["trace"]) if fixture.get("trace") else None
            result = {"output": fixture["output"], "token_usage": {}, "metadata": {
                "tft_trace": captured.to_dict() if captured else None,
                "trace_summary": captured.summary() if captured else "", "execution": "fixture",
            }}
        else:
            config = {**suite, "database": database, "model": variant.get("model"),
                      "prompt_candidates": {**prompts, **variant.get("prompts", {})}}
            if suite.get('captured_graphs'):
                config['captured_graph'] = suite['captured_graphs'][variant['name']]
                config['workspace_lineage'] = suite.get('workspace_lineage')
                # Managed prompt copies describe captured bases. Only explicit
                # historical overrides replace those bases during execution.
                config['prompt_candidates'] = variant.get('prompts', {})
                config['trace_prompts'] = {**prompts, **variant.get('prompts', {})}
            payload = {"operation": "evaluate", "config": config, "input": item["input"],
                       "identity": item.get("metadata", {})}
            result = isolated_operation(payload, resolve_eval_operation_timeout(suite.get("operation_timeout")))
            result.setdefault("token_usage", {})
    except Exception as exc:
        result = {"output": "", "metadata": {}, "token_usage": {},
                  "error": f"{type(exc).__name__}: {exc}"}
    result.setdefault("metadata", {})["latency_ms"] = (time.perf_counter() - started) * 1000
    return result


def score_attempt(item: dict, result: dict, prompts: dict) -> list[dict[str, Any]]:
    """Apply deterministic and rubric assertions with explicit failure semantics.

    Args:
        item: Frozen case with authored assertions.
        result: Actual execution output and evidence.
        prompts: Frozen grader template and assistant prompts.

    Returns:
        Named scores plus weighted_score and attempt_pass. Errors always fail.
    """
    from evals.langfuse.contracts import legacy_execution_item
    natural = isinstance(item["input"], str) or "input" not in item["input"]
    item = legacy_execution_item(item)
    scores = []
    metadata = result.get("metadata", {})
    for assertion in item["expected_output"]["assertions"]:
        threshold = float(assertion.get("threshold", 1))
        weight = float(assertion.get("weight", 1))
        error = result.get("error")
        value = 0.0
        comment = str(error or "")
        try:
            if not error:
                if assertion["kind"] == "trace":
                    trace = metadata.get("tft_trace")
                    check = evaluate_trace_check({**assertion["check"], "threshold": threshold},
                                                 trace_from_dict(trace) if trace else None,
                                                 output=result.get("output", ""))
                    value, comment = check.score, check.message
                elif assertion["kind"] == "selector":
                    value = selector_score(assertion["selector"], metadata["selection"])
                    comment = f"{assertion['selector']}: {value:.6f} (required {threshold})"
                elif assertion["kind"] == "rubric":
                    prompt = render_judge_prompt(prompts["judge"]["text"], item, result, assertion["rubric"])
                    response = isolated_operation({"operation": "judge", "config": {"family": "judge"},
                                                   "input": {"input": prompt}}, resolve_eval_operation_timeout())
                    if response.get("error"):
                        raise RuntimeError(response["error"])
                    grade = json.loads(response["output"])
                    value, comment = float(grade["score"]), str(grade["reason"])
                    if not math.isfinite(value) or not 0 <= value <= 1:
                        raise ValueError("Rubric score must be finite and between zero and one")
                else:
                    raise ValueError(f"Unknown assertion kind: {assertion['kind']}")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            value, comment = 0.0, error
        scores.append({"name": assertion["name"], "value": value,
                       "passed": not error and value >= threshold,
                       "threshold": threshold, "weight": weight, "comment": comment})
    passed = (natural or bool(scores)) and not result.get("error") and all(score["passed"] for score in scores)
    if natural:
        scores.extend([
            {"name": "execution_success", "value": float(not result.get("error")),
             "passed": not bool(result.get("error")), "threshold": 1, "weight": 0,
             "comment": str(result.get("error") or "Application execution succeeded.")},
            {"name": "contract_pass", "value": float(passed), "passed": passed, "threshold": 1,
             "weight": 0, "comment": "Every required deterministic check must pass."},
        ])
        return scores
    total_weight = sum(score["weight"] for score in scores)
    weighted = sum(score["value"] * score["weight"] for score in scores) / total_weight if total_weight else float(passed)
    scores.extend([
        {"name": "weighted_score", "value": weighted, "passed": passed, "threshold": None,
         "weight": 0, "comment": "Weighted mean of authored assertions; attempt_pass requires every assertion."},
        {"name": "attempt_pass", "value": float(passed), "passed": passed, "threshold": 1,
         "weight": 0, "comment": str(result.get("error") or "Every authored assertion must pass.")},
    ])
    return scores
