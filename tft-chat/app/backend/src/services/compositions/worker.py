"""Owned process execution with a durable queue and crash-safe terminal states."""

import logging
import multiprocessing
import os
import threading
import time
from sqlalchemy import select, text, update
from .storage import open_db, offline_enabled, local_store_path
from db.models import CompositionExperiment, CompositionSnapshot
from .models import ExperimentRequest, SnapshotData
from .execution import execute_snapshot
from .utils import local_queue_owner

logger = logging.getLogger(__name__)
WORKER_LOCK = 482193715


def watch_parent(parent_pid):
    """Terminate orphaned work if the owning backend disappears abruptly."""
    while os.getppid() == parent_pid:
        time.sleep(1)
    os._exit(1)


def execute_run(experiment_id, parent_pid, purpose="app"):
    """Run one experiment in a fresh interpreter with bounded parent ownership."""
    threading.Thread(target=watch_parent, args=(parent_pid,), daemon=True).start()
    started = time.monotonic()
    try:
        with open_db(purpose=purpose) as session:
            row = session.get(CompositionExperiment, experiment_id)
            request = ExperimentRequest.model_validate(row.request)
            snapshot = SnapshotData.model_validate(
                session.get(CompositionSnapshot, row.snapshot_id).payload
            )

        def progress(stage):
            """Persist the stage only while cancellation has not made the run terminal."""
            with open_db(purpose=purpose) as session:
                changed = session.execute(
                    update(CompositionExperiment)
                    .where(
                        CompositionExperiment.experiment_id == experiment_id,
                        CompositionExperiment.status == "running",
                    )
                    .values(stage=stage, elapsed_seconds=time.monotonic() - started)
                ).rowcount
                session.commit()
                if not changed:
                    raise InterruptedError("Run cancelled")

        result = execute_snapshot(snapshot, request, progress, run_id=experiment_id)
        with open_db(purpose=purpose) as session:
            session.execute(
                update(CompositionExperiment)
                .where(
                    CompositionExperiment.experiment_id == experiment_id,
                    CompositionExperiment.status == "running",
                )
                .values(
                    status="completed",
                    stage="completed",
                    elapsed_seconds=time.monotonic() - started,
                    result=result.model_dump(mode="json"),
                )
            )
            session.commit()
    except InterruptedError:
        return
    except Exception:
        logger.exception("Composition experiment failed")
        with open_db(purpose=purpose) as session:
            session.execute(
                update(CompositionExperiment)
                .where(
                    CompositionExperiment.experiment_id == experiment_id,
                    CompositionExperiment.status == "running",
                )
                .values(
                    status="failed",
                    stage="failed",
                    elapsed_seconds=time.monotonic() - started,
                    error="Experiment execution failed. Check the backend log and installed composition dependencies.",
                )
            )
            session.commit()


class CompositionWorker:
    """Serialize persistent jobs under a database-wide lock and own their processes."""

    def __init__(self, purpose="app"):
        """Create a stopped supervisor; the API lifecycle explicitly starts it."""
        self.purpose = purpose
        self.stopping = threading.Event()
        self.thread = None
        self.process = None

    def start(self):
        """Start nonblocking queue supervision when the feature and database are ready."""
        self.thread = threading.Thread(
            target=self.run, daemon=True, name="composition-supervisor"
        )
        self.thread.start()

    def close(self):
        """Stop owned work and wait for interrupted-state persistence on shutdown."""
        self.stopping.set()
        if self.thread:
            self.thread.join(timeout=10)

    def run(self):
        """Retry queue ownership after database outages without abandoning saved jobs."""
        while not self.stopping.is_set():
            try:
                path = (
                    local_store_path()
                    if self.purpose == "app" and offline_enabled()
                    else None
                )
                with local_queue_owner(path) as owned:
                    if owned:
                        self.serve_queue()
            except Exception:
                logger.exception(
                    "Composition worker unavailable; retrying queue ownership"
                )
            self.stopping.wait(1)

    def serve_queue(self):
        """Hold one advisory lock across recovery and owned child lifecycles."""
        with open_db(purpose=self.purpose) as lock_session:
            postgres = lock_session.bind.dialect.name == "postgresql"
            if postgres and not lock_session.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": WORKER_LOCK}
            ):
                return
            try:
                self.recover()
                while not self.stopping.is_set():
                    experiment_id = self.claim()
                    if experiment_id:
                        self.supervise(experiment_id)
                    else:
                        self.stopping.wait(0.5)
            finally:
                if postgres:
                    lock_session.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": WORKER_LOCK}
                    )

    def recover(self):
        """Mark unfinished active runs interrupted while retaining queued work."""
        with open_db(purpose=self.purpose) as session:
            session.execute(
                update(CompositionExperiment)
                .where(CompositionExperiment.status == "running")
                .values(
                    status="interrupted",
                    stage="interrupted",
                    error="Backend restarted before this run completed. Rerun reuses saved inputs.",
                )
            )
            session.commit()

    def claim(self):
        """Atomically claim the oldest queued run under the supervisor's global lock."""
        with open_db(purpose=self.purpose) as session:
            row = session.scalar(
                select(CompositionExperiment)
                .where(CompositionExperiment.status == "queued")
                .order_by(CompositionExperiment.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status, row.stage = "running", "starting"
            session.commit()
            return row.experiment_id

    def supervise(self, experiment_id):
        """Terminate cancelled children and record worker failures without losing queue state."""
        process = multiprocessing.get_context("spawn").Process(
            target=execute_run,
            args=(experiment_id, os.getpid(), self.purpose),
            daemon=True,
        )
        self.process = process
        try:
            process.start()
        except Exception:
            logger.exception("Composition worker process could not start")
            with open_db(purpose=self.purpose) as session:
                session.execute(
                    update(CompositionExperiment)
                    .where(
                        CompositionExperiment.experiment_id == experiment_id,
                        CompositionExperiment.status == "running",
                    )
                    .values(
                        status="failed",
                        stage="failed",
                        error="Worker process could not start. Rerun reuses saved inputs.",
                    )
                )
                session.commit()
            self.process = None
            return
        started = time.monotonic()
        try:
            while process.is_alive() and not self.stopping.wait(0.3):
                with open_db(purpose=self.purpose) as session:
                    row = session.get(CompositionExperiment, experiment_id)
                    if row.status != "running":
                        break
                    row.elapsed_seconds = time.monotonic() - started
                    session.commit()
        finally:
            if process.is_alive():
                process.terminate()
                process.join(3)
                if process.is_alive():
                    process.kill()
            process.join(3)
            self.process = None
            with open_db(purpose=self.purpose) as session:
                session.execute(
                    update(CompositionExperiment)
                    .where(
                        CompositionExperiment.experiment_id == experiment_id,
                        CompositionExperiment.status == "running",
                    )
                    .values(
                        status="interrupted" if self.stopping.is_set() else "failed",
                        stage="interrupted" if self.stopping.is_set() else "failed",
                        error="Backend shut down during execution."
                        if self.stopping.is_set()
                        else "Worker exited without a completed result.",
                        elapsed_seconds=time.monotonic() - started,
                    )
                )
                session.commit()
