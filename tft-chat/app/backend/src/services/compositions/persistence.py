"""Private snapshot reuse and append-only experiment history operations."""

import json
from functools import lru_cache
from uuid import uuid4
from sqlalchemy import select, update
from sqlalchemy.orm import defer
from .storage import open_db
from db.models import CompositionSnapshot, CompositionExperiment
from domain.compositions.registry import get_adapter, ALGORITHM_IDS
from .models import SnapshotData, ExperimentRequest, ExperimentHistory, SavedResult
from .source import capture_source
from .utils import (
    experiment_view,
    ensure_snapshot,
    snapshot_summaries,
    snapshot_summary,
    summarize_snapshot,
)


def create_experiment(request):
    """Freeze effective parameters and reusable source before appending a queue entry."""
    if request.algorithm_id not in ALGORITHM_IDS:
        raise ValueError("Unknown composition algorithm")
    adapter = get_adapter(request.algorithm_id)
    if (
        request.algorithm_version is not None
        and request.algorithm_version != adapter.algorithm_version
    ):
        raise ValueError(
            "Saved algorithm version is unavailable. Duplicate and edit to select the current implementation."
        )
    parameters = adapter.Parameters.model_validate(request.parameters).model_dump(
        mode="json"
    )
    snapshot = None
    if request.snapshot_id:
        with open_db() as session:
            # Reuse checks read the stored summary; loading the frozen boards here
            # would cost seconds per rerun for large or full-population snapshots.
            try:
                saved = snapshot_summary(session, request.snapshot_id)
            except LookupError:
                raise ValueError("Saved input snapshot was not found") from None
            session.commit()
            previous = session.scalar(
                select(CompositionExperiment)
                .where(CompositionExperiment.snapshot_id == request.snapshot_id)
                .order_by(CompositionExperiment.created_at)
                .limit(1)
            )
            if (
                previous is not None
                and previous.request["source_kind"] != request.source_kind
            ):
                raise ValueError("Changing the input source requires Refresh source")
            # Reusing a frozen sample must never silently reinterpret its seed/size.
            if (
                request.seed != saved.sampling_seed
                or request.sample_size != saved.requested_sample_size
            ):
                raise ValueError("Changing sample selection requires Refresh source")
            if request.full_population and not saved.includes_full_population:
                raise ValueError(
                    "This snapshot has no full population; use Refresh source"
                )
        snapshot_id, summary = request.snapshot_id, saved
    else:
        snapshot = capture_source(request)
        snapshot_id, summary = snapshot.context.snapshot_revision, summarize_snapshot(snapshot)
    effective = request.model_copy(
        update={
            "parameters": parameters,
            "snapshot_id": snapshot_id,
            "algorithm_version": adapter.algorithm_version,
        }
    )
    with open_db() as session:
        if snapshot is not None:
            ensure_snapshot(session, snapshot)
        row = CompositionExperiment(
            experiment_id=str(uuid4()),
            snapshot_id=snapshot_id,
            request=effective.model_dump(mode="json"),
            status="queued",
            stage="queued",
            elapsed_seconds=0,
        )
        session.add(row)
        session.commit()
        return experiment_view(row, summary)


def get_experiment(experiment_id):
    """Reopen a saved run without requiring the original source to remain available."""
    with open_db() as session:
        row = session.get(CompositionExperiment, experiment_id)
        if row is None or row.request.get("algorithm_id") != "hdbscan":
            raise LookupError("Experiment not found")
        summary = snapshot_summary(session, row.snapshot_id)
        session.commit()
        return experiment_view(row, summary)


def get_snapshot(snapshot_id):
    """Read a private input snapshot for display projection and worker execution."""
    with open_db() as session:
        row = session.get(CompositionSnapshot, snapshot_id)
        if row is None:
            raise LookupError("Snapshot not found")
        return SnapshotData.model_validate(row.payload)


def history():
    """Return the latest one hundred run summaries without heavy results."""
    with open_db() as session:
        # Results are omitted from history, so never transfer the result column.
        rows = session.scalars(
            select(CompositionExperiment)
            .where(CompositionExperiment.request["algorithm_id"].as_string() == "hdbscan")
            .options(defer(CompositionExperiment.result))
            .order_by(CompositionExperiment.created_at.desc())
            .limit(100)
        ).all()
        summaries = snapshot_summaries(session, {row.snapshot_id for row in rows})
        session.commit()
        return ExperimentHistory(
            experiments=tuple(
                experiment_view(row, summaries[row.snapshot_id], include_result=False)
                for row in rows
            )
        )


@lru_cache(maxsize=2)
def saved_result(experiment_id):
    """Load a completed run's display inputs once per backend process.

    Completed results are terminal and never rewritten, so caching them is safe;
    other states raise before anything is cached. Two entries cover comparison.
    """
    with open_db() as session:
        row = session.get(CompositionExperiment, experiment_id)
        if row is None or row.request.get("algorithm_id") != "hdbscan":
            raise LookupError("Experiment not found")
        if row.status != "completed" or row.result is None:
            raise ValueError("Experiment has no completed result")
        summary = snapshot_summary(session, row.snapshot_id)
        session.commit()
        model = row.result["model"]
        return SavedResult(
            experiment_id=row.experiment_id,
            snapshot_id=row.snapshot_id,
            request=ExperimentRequest.model_validate(row.request),
            context=summary.context,
            elapsed_seconds=row.elapsed_seconds,
            algorithm_id=model["algorithm_id"],
            algorithm_version=model["algorithm_version"],
            families=model["families"],
            populations=row.result["populations"],
        )


@lru_cache(maxsize=1)
def frozen_boards(snapshot_id):
    """Index one snapshot's boards and outcomes as compact JSON by observation ID.

    Display requests need at most fifty boards, so entries stay serialized and are
    validated only when returned. Insertion order preserves snapshot board order.

    Returns:
        Mapping of observation ID to ``(board_json, outcome_json_or_None)``.
    """
    with open_db() as session:
        payload = session.scalar(
            select(CompositionSnapshot.payload)
            .where(CompositionSnapshot.snapshot_id == snapshot_id)
        )
    if payload is None:
        raise LookupError("Snapshot not found")
    outcomes = {o["observation_id"]: o for o in payload["outcomes"]}
    return {
        board["observation_id"]: (
            json.dumps(board, separators=(",", ":")),
            json.dumps(outcomes[board["observation_id"]], separators=(",", ":"))
            if board["observation_id"] in outcomes else None,
        )
        for board in payload["boards"]
    }


def cancel_experiment(experiment_id):
    """Atomically cancel pending or active work; preserve every terminal result."""
    with open_db() as session:
        session.execute(
            update(CompositionExperiment)
            .where(
                CompositionExperiment.experiment_id == experiment_id,
                CompositionExperiment.request["algorithm_id"].as_string() == "hdbscan",
                CompositionExperiment.status.in_(("queued", "running")),
            )
            .values(status="cancelled", stage="cancelled")
        )
        session.commit()
    return get_experiment(experiment_id)


def rerun_experiment(experiment_id):
    """Append a new result using exactly the prior saved input and effective settings."""
    return create_experiment(get_experiment(experiment_id).request)
