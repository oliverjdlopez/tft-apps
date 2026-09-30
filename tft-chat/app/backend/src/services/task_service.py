"""Registered task service functions for the API layer."""

from __future__ import annotations

from typing import Any

from domain.tasks.transcript import (
    TRANSCRIPTION_TASK_DESCRIPTION,
    TRANSCRIPTION_TASK_NAME,
    run_transcription_pipeline,
)


def task_catalog() -> dict[str, Any]:
    return {
        "tasks": [
            {
                "name": TRANSCRIPTION_TASK_NAME,
                "description": TRANSCRIPTION_TASK_DESCRIPTION,
            }
        ]
    }


def run_task(name: str, *, input_text: str = "") -> dict[str, Any]:
    if name != TRANSCRIPTION_TASK_NAME:
        raise LookupError(f"Unknown task: {name}")

    try:
        result = run_transcription_pipeline(input_text)
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
