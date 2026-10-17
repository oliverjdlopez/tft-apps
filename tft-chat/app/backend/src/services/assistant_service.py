"""Assistant and task service functions for the API layer."""

from __future__ import annotations

from uuid import uuid4
from typing import Any

from agents.tracing import trace

from domain.assistants import Assistant
from domain.assistants.registry import current_registry
from services.task_service import task_catalog
from services.tracing_service import ensure_local_trace_processor, trace_file_path


def assistant_catalog() -> dict[str, Any]:
    registry = current_registry()
    assistants = []
    for name in registry.assistant_names:
        spec = registry.get_spec(name)
        assistants.append(
            {
                "name": name,
                "description": spec.description,
                "tools": list(registry.tool_names[name]),
                "handoffs": list(registry.handoff_names[name]),
            }
        )

    try:
        tasks = task_catalog()["tasks"]
    except Exception:  # noqa: BLE001 - keep assistant catalog available if tasks cannot load.
        tasks = []

    return {"assistants": assistants, "tasks": tasks}


def run_assistant(name: str, *, input_text: str = "") -> dict[str, Any]:
    try:
        assistant = Assistant(name, surface="api")
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
            result = assistant.run_sync(input_text).final_output
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
