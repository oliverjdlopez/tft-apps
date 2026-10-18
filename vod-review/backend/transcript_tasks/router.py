"""Thin VOD-owned endpoints for source-bound background task runs."""
from fastapi import APIRouter, Request, Response
from .models import StartRequest
from . import store

router = APIRouter()


@router.get("/api/transcript-tasks")
async def catalogue(request: Request):
    """Read service availability without hiding persisted results."""
    return await request.app.state.transcript_tasks.catalogue()


@router.post("/api/transcriptions/{source_id}/tasks/{task_name}")
async def start(source_id: str, task_name: str, request: Request, response: Response, body: StartRequest = StartRequest()):
    """Accept or reuse a short-lived submission; model work belongs to the service."""
    run, pending = await request.app.state.transcript_tasks.submit(source_id, task_name, body.rerun)
    response.status_code = 202 if pending else 200
    return run


@router.get("/api/transcriptions/{source_id}/tasks")
async def states(source_id: str, request: Request):
    """Read current attempts and latest success for the exact current source hash."""
    return request.app.state.transcript_tasks.states(source_id)


@router.get("/api/transcript-task-runs/{run_id}")
async def run(run_id: str):
    """Read a single persisted attempt by identity."""
    return store.get(run_id)
