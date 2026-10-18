"""Lifespan-owned workers and HTTP connection to the independent ChatTFT service."""
import asyncio
import os

import httpx
from fastapi import HTTPException

from .models import TASKS, TaskDefinition
from . import store
from .utils import assemble_input, resolve_output, source_title, transcript_hash

try:
    from .. import db
except ImportError:
    import db


class TranscriptTaskService:
    """Own at most two model requests and retain attempts beyond browser lifetimes."""

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None):
        """Configure isolated HTTP ownership without starting requests."""
        self.base_url = (base_url if base_url is not None else os.environ.get("VOD_CHAT_TFT_BASE_URL", "")).rstrip("/")
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(600, connect=3, pool=3))
        self.workers: set[asyncio.Task] = set()
        self.capacity = asyncio.Semaphore(2)
        self.closed = False

    async def start(self):
        """Recover interrupted persisted work without automatically regenerating it."""
        store.recover()

    async def stop(self):
        """Cancel and await local workers before closing the owned HTTP client."""
        self.closed = True
        tasks = list(self.workers)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.aclose()

    async def catalogue(self) -> dict:
        """Filter upstream metadata to the two supported transcript contracts."""
        definitions = [item.model_dump() for item in TASKS.values()]
        reason = "ChatTFT is not configured. Set VOD_CHAT_TFT_BASE_URL to enable transcript actions."
        available_names = set()
        if self.base_url:
            try:
                response = await self.client.get(f"{self.base_url}/api/assistants", timeout=3)
                response.raise_for_status()
                remote = response.json()["tasks"]
                if not isinstance(remote, list) or any(not isinstance(item, dict) for item in remote):
                    raise ValueError("Malformed ChatTFT catalogue")
                for item in remote:
                    name = item.get("name")
                    if name in TASKS:
                        parsed = TaskDefinition.model_validate(item)
                        local = TASKS[name]
                        if (parsed.version, parsed.output_kind, parsed.requires_timestamps) == (local.version, local.output_kind, local.requires_timestamps):
                            available_names.add(name)
                            definitions = [parsed.model_dump() if d["name"] == name else d for d in definitions]
                reason = "ChatTFT does not expose the supported task contract."
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                reason = "ChatTFT is unavailable. Saved results and transcripts remain available."
        return {"tasks": [{**item, "available": item["name"] in available_names, "reason": None if item["name"] in available_names else reason} for item in definitions], "available": bool(available_names), "reason": None if available_names else reason}

    def states(self, source_id: str) -> dict:
        """Return active, latest, and previous successful attempts independently."""
        source = db.get_transcription_task(source_id, include_segments=True)
        history = store.runs(source_id, transcript_hash(source))
        states = []
        for name in TASKS:
            attempts = [run for run in history if run["task_name"] == name]
            states.append({
                "name": name,
                "active_run": next((run for run in attempts if run["status"] in ("queued", "running")), None),
                "latest_run": attempts[0] if attempts else None,
                "successful_run": next((run for run in attempts if run["status"] == "completed"), None),
            })
        return {"tasks": states}

    async def submit(self, source_id: str, name: str, rerun: bool = False) -> tuple[dict, bool]:
        """Validate a snapshot, atomically reuse/insert, then schedule owned work."""
        if name not in TASKS:
            raise HTTPException(404, "Unknown transcript task")
        source = db.get_transcription_task(source_id, include_segments=True)
        definition = TASKS[name]
        body = assemble_input(source, source_title(source), definition.requires_timestamps)
        digest = transcript_hash(source)
        # Saved work can be reused without a reachable upstream service.
        existing, _ = store.choose(source_id, name, definition.version, digest, rerun, create=False)
        if existing:
            return existing, existing["status"] != "completed"
        catalogue = await self.catalogue()
        item = next(item for item in catalogue["tasks"] if item["name"] == name)
        if not item["available"] or self.closed:
            raise HTTPException(503, item["reason"] or "Backend is shutting down")
        run, created = store.choose(source_id, name, definition.version, digest, rerun)
        if created:
            worker = asyncio.create_task(self.execute(run, source, body), name=f"transcript-task-{run['id']}")
            self.workers.add(worker)
            worker.add_done_callback(self.workers.discard)
        return run, run["status"] != "completed"

    def check_source(self, run: dict):
        """Reject stale source data before execution and before attaching output."""
        if transcript_hash(db.get_transcription_task(run["transcription_task_id"], include_segments=True)) != run["transcript_hash"]:
            raise ValueError("Transcript changed. Start a new attempt for the current source.")

    async def execute(self, run: dict, source: dict, body: str):
        """Execute once within the per-backend concurrency bound and persist failures."""
        code = "upstream_failure"
        try:
            async with self.capacity:
                self.check_source(run)
                store.update(run["id"], "running")
                response = await self.client.post(f"{self.base_url}/api/assistants/tasks/{run['task_name']}/run", json={"input": body})
                response.raise_for_status()
                payload = response.json()
                if payload.get("ok") is not True or payload.get("task") != run["task_name"]:
                    raise ValueError(payload.get("error") or "Invalid ChatTFT task response")
                output = resolve_output(payload.get("result"), source, TASKS[run["task_name"]].requires_timestamps)
                self.check_source(run)
                store.update(run["id"], "completed", output=output)
        except asyncio.CancelledError:
            store.update(run["id"], "failed", error_code="interrupted", error="Backend stopped. Retry manually to start a new attempt.")
            raise
        except httpx.TimeoutException:
            store.update(run["id"], "failed", error_code="timeout", error="ChatTFT timed out. The upstream call may still be running. A manual retry starts a new attempt.")
        except Exception as exc:
            store.update(run["id"], "failed", error_code=code, error=str(exc))
