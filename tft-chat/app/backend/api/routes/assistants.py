"""Assistant HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from services.assistant_service import assistant_catalog, run_assistant
from services.task_service import run_task

router = APIRouter(prefix="/api/assistants", tags=["assistants"])


class AssistantRunBody(BaseModel):
    input: str = ""


@router.get("")
def assistants() -> dict[str, Any]:
    return assistant_catalog()


@router.post("/tasks/{name}/run")
def run_registered_task(name: str, body: AssistantRunBody) -> dict[str, Any]:
    try:
        return run_task(name, input_text=body.input)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.post("/{name}/run")
def run(name: str, body: AssistantRunBody) -> dict[str, Any]:
    try:
        return run_assistant(name, input_text=body.input)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None
