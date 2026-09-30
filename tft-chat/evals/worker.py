"""Isolated one-operation SDK worker for frozen evaluation attempts."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import json
import os
import sys
from typing import Any

from evals.database import eval_database_override, resolve_eval_target
from evals.trace import extract_trace
from evals.utils import selector_case, eval_graph_instructions


def run_assistant(prompt: str, config: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    """Execute the real registry graph in an eval database and trace scope.

    Args:
        prompt: Frozen user request text.
        config: Assistant, model, turn limit and optional system prompt candidate.
        identity: Stable suite and case metadata from the frozen dataset.

    Returns:
        Final answer and normalized trace/provenance metadata.
    """
    from agents import ModelSettings, RunConfig, Runner
    from agents.tracing import trace
    from domain.assistants import create_assistant, render_assistant_input

    name = config["assistant"]
    target = resolve_eval_target(config.get("database"))
    with eval_database_override(target), trace("tft-eval-case", metadata={
        "suite": identity.get("suite", name), "case": identity.get("case", ""), "assistant": name,
    }) as case_trace:
        graph_instructions = eval_graph_instructions(name, prompt, config.get("prompt_candidates", {}))
        instructions = graph_instructions[name]
        agent = create_assistant(name, model=config.get("model"), instructions=instructions,
                                 instructions_by_name=graph_instructions)
        result = Runner.run_sync(agent, input=config.get("messages") or render_assistant_input(name, prompt), max_turns=config.get("max_turns") or 10,
                                 **({"run_config": RunConfig(model_settings=ModelSettings(**config["model_settings"]))}
                                    if config.get("model_settings") else {}))
    captured = extract_trace(result, trace_id=case_trace.trace_id)
    usage = result.context_wrapper.usage
    return {"output": (result.final_output.model_dump(mode="json") if hasattr(result.final_output, "model_dump") else result.final_output), "token_usage": {
        "prompt": usage.input_tokens, "completion": usage.output_tokens,
        "total": usage.total_tokens, "numRequests": usage.requests,
    }, "metadata": {
        "tft_trace": captured.to_dict(), "trace_summary": captured.summary(),
        "trace_url": f"https://platform.openai.com/traces/trace?trace_id={case_trace.trace_id}",
        "model": str(agent.model), "instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
        "dataset": config.get("dataset", target.database),
        "database": target.database,
        "instruction_hashes": {key: hashlib.sha256(value.encode()).hexdigest() for key, value in graph_instructions.items()},
    }}


def run_judge(prompt: str, config: dict[str, Any]) -> dict[str, Any]:
    """Generate a structured rubric score for the shared evaluation scorer.

    Args:
        prompt: Complete evidence and rubric rendered from a frozen template.
        config: Optional grader model and request timeout.

    Returns:
        JSON score/reason text; the evaluation scorer owns the pass/fail decision.
    """
    from openai import OpenAI
    from core.config import load_config

    settings = load_config()
    model = config.get("model") or os.environ.get("EVAL_JUDGE_MODEL") or settings.models.openai_model
    client = OpenAI(api_key=settings.secrets.openai_api_key, max_retries=0,
                    timeout=float(os.environ.get("EVAL_JUDGE_TIMEOUT_SECONDS", "45")))
    response = client.responses.create(model=model, input=prompt, text={"format": {
        "type": "json_schema", "name": "eval_score", "strict": True,
        "schema": {"type": "object", "properties": {
            "score": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        }, "required": ["score", "reason"], "additionalProperties": False},
    }})
    if response.status != "completed" or not response.output_text:
        raise ValueError("Rubric model did not return a complete score")
    return {"output": response.output_text, "token_usage": {
        "prompt": response.usage.input_tokens, "completion": response.usage.output_tokens,
        "total": response.usage.total_tokens, "numRequests": 1,
    }, "metadata": {"model": model}}


def execute(payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one neutral operation without importing unused evaluation families.

    Args:
        payload: JSON operation, config, input, and identity sent by the parent.

    Returns:
        Execution output, token usage, and trace metadata.
    """
    if payload["operation"] not in {"evaluate", "judge"}:
        raise ValueError("Unknown evaluation operation")
    config = payload["config"]
    prompt = payload["input"]["input"]
    identity = payload.get("identity", {})
    family = config["family"]
    if family == "judge":
        return run_judge(prompt, config)
    if family == "assistant":
        if payload["input"].get("messages"):
            config = {**config, "messages": payload["input"]["messages"]}
        return run_assistant(prompt, config, identity)
    import domain.assistants
    if family == "context_selection":
        from evals.context_selection.provider import evaluate
    elif family == "skill_selection":
        from evals.skill_selection.provider import evaluate
    else:
        raise ValueError(f"Unknown eval family: {family}")
    case = selector_case(payload["input"], identity)
    metrics = evaluate(case,
                       live=config.get("execution") == "live", model=config.get("model"))
    return {"output": metrics.get("selected", metrics.get("selected_skills", [])), "metadata": {"selection": metrics}}


def terminate_worker(signum, frame) -> None:
    """Flush completed spans on timeout before the parent enforces its kill deadline."""
    try:
        from agents.tracing import get_trace_provider
        get_trace_provider().force_flush()
        from opentelemetry import trace
        provider = trace.get_tracer_provider()
        if hasattr(provider, 'force_flush'):
            provider.force_flush(timeout_millis=1000)
    finally:
        raise SystemExit(124)


def main() -> None:
    """Keep SDK logging off the stdout JSON transport and flush trace exports."""
    import signal
    signal.signal(signal.SIGTERM, terminate_worker)
    payload = json.load(sys.stdin)
    try:
        from common.langfuse_tracing import worker_trace
        with redirect_stdout(sys.stderr), worker_trace(payload.get('trace_context'),
                payload.get('config', {}).get('prompt_candidates', {})):
            result = execute(payload)
            if payload.get("config", {}).get("execution") == "live":
                from agents.tracing import get_trace_provider
                get_trace_provider().force_flush()
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {exc}"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
