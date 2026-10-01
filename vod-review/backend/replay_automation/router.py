"""Schedule configuration, status, and explicit Run now HTTP boundary."""

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from . import store
from .models import ReplaySchedule

router = APIRouter(prefix="/api/replay-automation", tags=["Creator imports"])


def runtime(request: Request):
    """Resolve the one automation owner started by the backend lifespan."""
    owner = getattr(request.app.state, "replay_automation", None)
    if owner is None:
        raise HTTPException(503, "Creator scheduling is not initialized")
    return owner


@router.get("")
async def get_status(request: Request) -> dict:
    """Read persisted configuration, run errors, and import progress."""
    runtime(request)
    return store.status()


@router.put("")
async def configure(settings: ReplaySchedule, request: Request) -> dict:
    """Save a daily schedule; saving never triggers an immediate download."""
    owner = runtime(request)
    store.save_settings(settings, datetime.now(timezone.utc))
    owner.wake.set()
    return store.status()


@router.post("/run", status_code=202)
async def run_now(request: Request) -> dict:
    """Start an explicit scan using the saved creators and lookback window."""
    owner = runtime(request)
    run = owner.run_now()
    return {"run_id": run["id"], "status": run["status"]}
