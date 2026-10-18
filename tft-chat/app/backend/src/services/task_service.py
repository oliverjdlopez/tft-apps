"""Registered task service functions for the API layer."""

from __future__ import annotations

from typing import Any

from domain.tasks.key_moments import run_key_moments
from domain.tasks.utils import validate_input_budget

from domain.tasks.transcript import (
    TRANSCRIPTION_TASK_DESCRIPTION,
    TRANSCRIPTION_TASK_NAME,
    run_transcription_pipeline,
)


# Versions change with prompts, input construction, or output contracts.
TASKS = {
    TRANSCRIPTION_TASK_NAME: {
        "name": TRANSCRIPTION_TASK_NAME, "label": "Distill transcript",
        "description": TRANSCRIPTION_TASK_DESCRIPTION, "version": 1,
        "requires_timestamps": False, "output_kind": "markdown",
    },
    "find_key_moments": {
        "name": "find_key_moments", "label": "Find key moments",
        "description": "Find consequential passages grounded in the speaker's words.",
        "version": 1, "requires_timestamps": True, "output_kind": "key_moments",
    },
}


def task_catalog() -> dict[str, Any]:
    """Expose the small public task catalogue independently of assistant discovery."""
    return {"tasks": list(TASKS.values())}


def run_task(name: str, *, input_text: str = "") -> dict[str, Any]:
    if name not in TASKS:
        raise LookupError(f"Unknown task: {name}")

    try:
        if name == TRANSCRIPTION_TASK_NAME:
            validate_input_budget(input_text)
        runner = {TRANSCRIPTION_TASK_NAME: run_transcription_pipeline, "find_key_moments": run_key_moments}[name]
        result = runner(input_text)
    except Exception as e:  # noqa: BLE001 - API should show task failures.
        return {
            "ok": False,
            "task": name,
            "error": f"{type(e).__name__}: {e}",
        }

    return {
        "ok": True,
        "task": name,
        "result": result,
    }


__all__ = ["run_task", "task_catalog"]
