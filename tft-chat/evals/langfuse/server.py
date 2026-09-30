"""Authenticated native Langfuse triggers and a durable local experiment queue."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import hmac
import logging
import os
from pathlib import Path
import subprocess
import threading
from time import perf_counter
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from .jobs import JobStore
from .models import ExperimentTrigger

logger = logging.getLogger(__name__)


class ExperimentService:
    """Own the SDK client and single queue consumer for one local workspace."""

    def __init__(self, snapshots: Path, runtime: Path, client_factory: Callable[[], Any]):
        """Defer SDK construction until application startup, allowing offline imports."""
        self.snapshots = snapshots
        self.runtime = runtime
        self.workspace = None
        self.jobs = JobStore(runtime)
        self.client_factory = client_factory
        self.client: Any = None
        self.stop = threading.Event()
        self.wakeup = threading.Event()
        self.thread: threading.Thread | None = None
        self.consumer_error: str | None = None

    def start(self) -> None:
        """Recover interrupted jobs and start a single bounded experiment consumer."""
        self.stop.clear()
        self.consumer_error = None
        self.client = self.client_factory()
        if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"):
            from .workspace import Workspace
            self.workspace = Workspace(os.environ.get("LANGFUSE_BASE_URL", "http://localhost:15510"),
                                       os.environ["LANGFUSE_PUBLIC_KEY"], os.environ["LANGFUSE_SECRET_KEY"])
        for job_id in self.jobs.recover():
            self.publish_status(job_id, "interrupted", {"reason": "Service restarted during execution"})
        self.thread = threading.Thread(target=self.consume, name="langfuse-experiments", daemon=True)
        self.thread.start()

    def close(self) -> None:
        """Stop accepting queued work; active isolated operations retain their timeout."""
        self.stop.set()
        self.wakeup.set()
        if self.thread:
            self.thread.join(timeout=1)
        if self.client is not None:
            self.client.flush()
        if self.workspace is not None and not (self.thread and self.thread.is_alive()):
            self.workspace.close()

    def publish_status(self, job_id: str, state: str, details: dict[str, Any]) -> None:
        """Make asynchronous job failures and export outcomes visible in native traces."""
        try:
            self.client.create_event(
                name="chattft-experiment-job", input={"job_id": job_id},
                output={"state": state, **details}, metadata={"job_id": job_id, "state": state},
                level="ERROR" if state in {"failed", "interrupted"} else "DEFAULT",
            )
            self.client.flush()
        except Exception:
            logger.exception("Unable to publish job status %s; durable status is retained", job_id)

    def submit(self, trigger: ExperimentTrigger) -> dict[str, Any]:
        """Freeze and export UI-authored content before acknowledging execution."""
        from .content import export_snapshot, fetch_bundle, load_snapshot, validate_bundle
        from .utils import catalog_revision

        preparation_started = perf_counter()
        revision = catalog_revision(self.snapshots)
        config = trigger.config.model_dump()
        if config["action"] == "replay":
            bundle = load_snapshot(config["snapshot"], self.snapshots)
            # A replay's original selection, variants and grading definitions are authoritative.
            snapshot_id = config["snapshot"]
            bundle["config"]["action"] = "run"
        else:
            bundle = fetch_bundle(self.client, trigger.dataset_name, config, self.snapshots)
            if trigger.dataset_id and bundle.get("dataset_id") != trigger.dataset_id:
                raise ValueError("Dataset identity does not match its name")
            bundle = validate_bundle(bundle)
            snapshot_id = export_snapshot(bundle, self.snapshots, expected_revision=revision)
        if (bundle.get("dataset_name") or f"chattft/{bundle['suite']['name']}") != trigger.dataset_name:
            raise ValueError("Snapshot belongs to another dataset")
        bundle = validate_bundle(bundle)
        bundle["provenance"] = self.provenance()
        bundle["snapshot_id"] = snapshot_id
        # Native Langfuse abandons the webhook after 20 seconds. Never enqueue
        # model calls after slow preparation has exhausted the shorter budget.
        if perf_counter() - preparation_started >= 15:
            raise ValueError("Evaluation preparation exceeded 15 seconds; no evaluation was scheduled")
        job_id = self.jobs.submit(bundle, snapshot_id, exported=config["action"] == "export")
        if config["action"] == "export":
            self.publish_status(job_id, "exported", {"snapshot": snapshot_id})
        else:
            self.wakeup.set()
        return {"job_id": job_id, "snapshot": snapshot_id, "status_url": f"/jobs/{job_id}"}

    def provenance(self) -> dict[str, str]:
        """Record source identity without copying repository content into traces."""
        root = Path(__file__).resolve().parents[2]
        try:
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
            diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=root, stderr=subprocess.DEVNULL)
            untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root, stderr=subprocess.DEVNULL)
            fingerprint = hashlib.sha256(diff)
            for raw in sorted(part for part in untracked.split(b"\0") if part):
                path = root / os.fsdecode(raw)
                fingerprint.update(raw + b"\0")
                fingerprint.update(hashlib.sha256(os.fsencode(os.readlink(path)) if path.is_symlink() else path.read_bytes()).digest())
            return {"git_revision": revision, "working_tree_fingerprint": fingerprint.hexdigest()}
        except (OSError, subprocess.CalledProcessError):
            return {"git_revision": os.environ.get("CHAT_TFT_GIT_REVISION", "unavailable"),
                    "working_tree_fingerprint": os.environ.get("CHAT_TFT_WORKING_TREE_FINGERPRINT", "unavailable")}

    def consume(self) -> None:
        """Execute one job at a time so per-run concurrency is also a service cap."""
        from .experiments import run_bundle

        while not self.stop.is_set():
            try:
                pending = self.jobs.pending_scores()
                if pending:
                    from .grading import reconcile_report
                    if self.workspace is None:
                        raise RuntimeError("Native score reconciliation requires configured workspace credentials")
                    for waiting in pending:
                        try:
                            report = reconcile_report(self.workspace, waiting['result'], waiting['bundle']['grading'])
                            if report['state'] == 'awaiting_scores':
                                self.jobs.awaiting_scores(waiting['id'], report)
                            else:
                                state = 'completed' if report['passed'] else 'failed'
                                self.jobs.finish(waiting['id'], state, result=report)
                                self.publish_status(waiting['id'], state, {'result': report})
                        except Exception as exc:
                            import time
                            if time.time() >= waiting['result']['grading_deadline']:
                                waiting['result'].update(state='completed', passed=False,
                                                         grading_error='Incomplete native grading: ' + type(exc).__name__)
                                self.jobs.finish(waiting['id'], 'failed', result=waiting['result'],
                                                 error='Incomplete native grading: ' + type(exc).__name__)
                    self.stop.wait(2)
                    continue
                job = self.jobs.claim()
            except Exception as exc:
                self.consumer_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Experiment queue consumer stopped; service is unhealthy")
                return
            if job is None:
                self.wakeup.wait(timeout=1)
                self.wakeup.clear()
                continue
            job_id = job["id"]
            self.publish_status(job_id, "running", {"snapshot": job["snapshot"]})
            try:
                result = run_bundle(job["bundle"], self.client, group_id=job_id)
                if result.get("state") == "awaiting_scores":
                    self.jobs.awaiting_scores(job_id, result)
                    self.publish_status(job_id, "awaiting_scores", {"snapshot": job["snapshot"]})
                    continue
                state = "completed" if result.get("passed") else "failed"
                self.jobs.finish(job_id, state, result=result)
                self.publish_status(job_id, state, {"snapshot": job["snapshot"], "result": result})
            except Exception as exc:
                self.jobs.finish(job_id, "failed", error=f"{type(exc).__name__}: {exc}")
                self.publish_status(job_id, "failed", {"snapshot": job["snapshot"], "error": str(exc)})
                logger.exception("Experiment job %s failed", job_id)


def create_client() -> Any:
    """Construct the optional SDK only when the experiment service starts."""
    from langfuse import Langfuse
    return Langfuse(timeout=5)


def create_app(*, service: ExperimentService | None = None, token: str | None = None) -> FastAPI:
    """Build the API with injectable lifecycle dependencies for integration tests."""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Start queue processing after configuration is available and release it on exit."""
        nonlocal service, token
        token = token or os.environ.get("LANGFUSE_EXPERIMENT_TOKEN")
        if not token:
            raise RuntimeError("LANGFUSE_EXPERIMENT_TOKEN is required")
        if service is None:
            root = Path(__file__).parent
            service = ExperimentService(
                Path(os.environ.get("LANGFUSE_SNAPSHOT_DIR", str(root / "snapshots"))),
                Path(os.environ.get("LANGFUSE_RUNTIME_DIR", str(root / ".runtime"))), create_client,
            )
        service.start()
        app.state.service = service
        yield
        service.close()

    app = FastAPI(title="ChatTFT Langfuse experiments", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Report process readiness without exposing credentials or job inputs."""
        if isinstance(service, ExperimentService) and (
                service.consumer_error or not service.thread or not service.thread.is_alive()):
            raise HTTPException(status_code=503, detail="Experiment queue consumer is unavailable")
        return {"status": "ready"}

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        """Require the private native webhook credential on non-health operations."""
        from fastapi.responses import JSONResponse
        if request.url.path != "/health":
            supplied = request.headers.get("authorization", "")
            if not token or not hmac.compare_digest(supplied, f"Bearer {token}"):
                return JSONResponse(status_code=401, content={"detail": "Invalid experiment credential"})
        return await call_next(request)

    @app.post("/experiments", status_code=202)
    def submit(trigger: ExperimentTrigger) -> dict[str, Any]:
        """Validate native JSON settings, freeze sources, and acknowledge the job."""
        assert service is not None
        try:
            return service.submit(trigger)
        except (ValueError, ValidationError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Unable to prepare experiment")
            raise HTTPException(status_code=503, detail="Unable to prepare experiment; inspect service logs") from exc

    @app.get("/jobs/{job_id}")
    def job_status(job_id: str) -> dict[str, Any]:
        """Expose durable status for launcher automation and operational diagnosis."""
        assert service is not None
        result = service.jobs.get(job_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Unknown job")
        return result

    from .playground import router
    app.include_router(router)
    return app


app = create_app()
