"""Assistant and task service functions for the API layer."""

from __future__ import annotations

from uuid import uuid4
from typing import Any

from agents import Runner
from agents.tracing import trace

from domain.assistants import (
    assistant_handoff_names,
    assistant_spec,
    assistant_tool_names,
    build_assistant_instructions,
    create_assistant,
    list_assistants,
    render_assistant_input,
)
from services.task_service import task_catalog
from services.tracing_service import ensure_local_trace_processor, trace_file_path


def assistant_catalog() -> dict[str, Any]:
    assistants = []
    for name in list_assistants():
        assistants.append(
            {
                "name": name,
                "description": assistant_spec(name).description,
                "tools": assistant_tool_names(name),
                "handoffs": assistant_handoff_names(name),
            }
        )

    try:
        tasks = task_catalog()["tasks"]
    except Exception:  # noqa: BLE001 - keep assistant catalog available if tasks cannot load.
        tasks = []

    return {"assistants": assistants, "tasks": tasks}


def run_assistant(name: str, *, input_text: str = "") -> dict[str, Any]:
    try:
        agent = create_assistant(
            name,
            instructions=build_assistant_instructions(name, input_text),
        )
    except KeyError:
        raise LookupError(f"Unknown assistant: {name}") from None

    run_id = uuid4().hex
    ensure_local_trace_processor()
    metadata = {
        "run_id": run_id,
        "assistant": name,
        "input_chars": str(len(input_text)),
    }
    current_trace = None
    try:
        with trace("tft-assistant", group_id=run_id, metadata=metadata) as current_trace:
            result = Runner.run_sync(
                agent,
                input=render_assistant_input(name, input_text),
            ).final_output
    except Exception as e:  # noqa: BLE001 - API should show assistant failures.
        trace_id = getattr(current_trace, "trace_id", None)
        return {
            "ok": False,
            "assistant": name,
            "run_id": run_id,
            "trace_id": trace_id,
            "trace_path": str(trace_file_path(trace_id)) if trace_id else None,
            "error": f"{type(e).__name__}: {e}",
        }

    trace_id = getattr(current_trace, "trace_id", None)
    return {
        "ok": True,
        "assistant": name,
        "run_id": run_id,
        "trace_id": trace_id,
        "trace_path": str(trace_file_path(trace_id)) if trace_id else None,
        "result": result,
    }


__all__ = ["assistant_catalog", "run_assistant"]
