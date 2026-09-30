"""Snapshot hashing, safe projections, and population helpers."""

import hashlib
import json
import random
import os
from contextlib import contextmanager
from functools import lru_cache
from .models import (
    CompositionContext,
    SnapshotData,
    ExperimentView,
    ExperimentRequest,
    PopulationResult,
)
from domain.compositions.profiles import aggregate_profiles


def make_snapshot(
    request,
    boards,
    outcomes,
    patch,
    set_number,
    queue_id,
    eligible=None,
    sample_ids=None,
):
    """Content-address anonymous inputs and seeded selection without source identities."""
    if sample_ids is None:
        selected = random.Random(request.seed).sample(
            list(boards), min(request.sample_size, len(boards))
        )
        sample_ids = tuple(
            b.observation_id for b in sorted(selected, key=lambda b: b.observation_id)
        )
        eligible = len(boards)
        if not request.full_population:
            boards = tuple(b for b in boards if b.observation_id in set(sample_ids))
            outcomes = tuple(o for o in outcomes if o.observation_id in set(sample_ids))
    snapshot = SnapshotData(
        context=CompositionContext(
            source_kind="experiment",
            population_kind="discovery_sample",
            patch=patch,
            set_number=set_number,
            queue_id=queue_id,
            snapshot_revision="pending",
            taxonomy_revision="unpublished.v1",
            feature_revision="structure.v1",
            algorithm_id=None,
            algorithm_version=None,
            experiment_id=None,
        ),
        boards=boards,
        outcomes=outcomes,
        sample_ids=sample_ids,
        eligible_boards=eligible,
        includes_full_population=request.full_population,
        sampling_seed=request.seed,
        requested_sample_size=request.sample_size,
    )
    revision = hashlib.sha256(
        json.dumps(
            snapshot.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return snapshot.model_copy(
        update={
            "context": snapshot.context.model_copy(
                update={"snapshot_revision": revision}
            )
        }
    )


def experiment_view(row, summary, include_result=True):
    """Project only declared fields; ORM identifiers and worker errors stay private.

    Args:
        row: Saved experiment; its result column is read only when included.
        summary: The run's ``SnapshotSummary``; the frozen boards are never needed.
        include_result: False for history rows, which omit results entirely.
    """
    return ExperimentView(
        experiment_id=row.experiment_id,
        snapshot_id=row.snapshot_id,
        created_at=row.created_at.isoformat(),
        status=row.status,
        stage=row.stage,
        elapsed_seconds=row.elapsed_seconds,
        request=ExperimentRequest.model_validate(row.request),
        context=summary.context,
        eligible_boards=summary.eligible_boards,
        sample_boards=summary.sample_boards,
        error=row.error,
        result=result_view(row.result) if include_result and row.result else None,
    )


def result_view(stored):
    """Validate only the run-view subset of a stored result JSON document.

    Selecting fields before validation skips the fitted state, native discovery
    labels, and per-candidate evidence, which dominate stored result size.
    """
    from .models import ExperimentResultView

    model = {k: v for k, v in stored["model"].items() if k != "state"}
    summary_fields = ("observation_id", "status", "family_id", "variation_id")
    return ExperimentResultView.model_validate({
        "model": model,
        "diagnostics": stored["diagnostics"],
        "populations": [
            {
                **{k: v for k, v in population.items() if k != "assignments"},
                "assignments": [
                    {k: a[k] for k in summary_fields} for a in population["assignments"]
                ],
            }
            for population in stored["populations"]
        ],
    })


def population_result(kind, boards, outcomes, families, assignments, minimum):
    """Aggregate classification coverage separately from native discovery labels."""
    return PopulationResult(
        population_kind=kind,
        assignments=assignments,
        profiles=aggregate_profiles(boards, outcomes, families, assignments, minimum),
        coverage=sum(a.status == "assigned" for a in assignments) / len(boards)
        if boards
        else None,
        ambiguity=sum(a.status == "ambiguous" for a in assignments) / len(boards)
        if boards
        else None,
    )


# =====================================================================
# Persistence snapshot helpers
# Content-addressed snapshots can be requested concurrently by two clients.
# A savepoint isolates the expected unique-key race from the queued result.
# =====================================================================


def ensure_snapshot(session, snapshot):
    """Reuse immutable inputs even when another client inserts the same hash first."""
    from sqlalchemy.exc import IntegrityError
    from db.models import CompositionSnapshot

    key = snapshot.context.snapshot_revision
    if session.get(CompositionSnapshot, key) is None:
        try:
            with session.begin_nested():
                session.add(
                    CompositionSnapshot(
                        snapshot_id=key, payload=snapshot.model_dump(mode="json")
                    )
                )
                session.flush()
        except IntegrityError:
            if session.get(CompositionSnapshot, key) is None:
                raise
    store_snapshot_summary(session, key, summarize_snapshot(snapshot))


def summarize_snapshot(snapshot):
    """Reduce validated snapshot data to its stored ``SnapshotSummary``."""
    from .models import SnapshotSummary

    return SnapshotSummary(
        context=snapshot.context,
        eligible_boards=snapshot.eligible_boards,
        sample_boards=len(snapshot.sample_ids),
        includes_full_population=snapshot.includes_full_population,
        sampling_seed=snapshot.sampling_seed,
        requested_sample_size=snapshot.requested_sample_size,
    )


def store_snapshot_summary(session, snapshot_id, summary):
    """Insert a summary once, tolerating a concurrent writer for the same snapshot."""
    from sqlalchemy.exc import IntegrityError
    from db.models import CompositionSnapshotSummary

    if session.get(CompositionSnapshotSummary, snapshot_id) is not None:
        return
    try:
        with session.begin_nested():
            session.add(CompositionSnapshotSummary(
                snapshot_id=snapshot_id, summary=summary.model_dump(mode="json"),
            ))
            session.flush()
    except IntegrityError:
        if session.get(CompositionSnapshotSummary, snapshot_id) is None:
            raise


def snapshot_summaries(session, snapshot_ids):
    """Return ``SnapshotSummary`` values by ID, backfilling snapshots saved earlier.

    Snapshots created before the summary table existed are summarized once with
    database JSON extraction, so Python never materializes their board payload.
    The caller commits to keep any backfilled rows.
    """
    from sqlalchemy import func, select
    from db.models import CompositionSnapshot, CompositionSnapshotSummary
    from .models import SnapshotSummary

    wanted = set(snapshot_ids)
    found = {
        row.snapshot_id: SnapshotSummary.model_validate(row.summary)
        for row in session.scalars(
            select(CompositionSnapshotSummary)
            .where(CompositionSnapshotSummary.snapshot_id.in_(wanted))
        )
    }
    missing = wanted - found.keys()
    if missing:
        payload = CompositionSnapshot.payload
        rows = session.execute(
            select(
                CompositionSnapshot.snapshot_id,
                payload["context"],
                payload["eligible_boards"].as_integer(),
                func.json_array_length(payload["sample_ids"]),
                payload["includes_full_population"].as_boolean(),
                payload["sampling_seed"].as_integer(),
                payload["requested_sample_size"].as_integer(),
            ).where(CompositionSnapshot.snapshot_id.in_(missing))
        ).all()
        for snapshot_id, context, eligible, samples, full, seed, requested in rows:
            summary = SnapshotSummary(
                context=context, eligible_boards=eligible, sample_boards=samples,
                includes_full_population=full, sampling_seed=seed,
                requested_sample_size=requested,
            )
            store_snapshot_summary(session, snapshot_id, summary)
            found[snapshot_id] = summary
    return found


def snapshot_summary(session, snapshot_id):
    """Return one snapshot's summary or raise ``LookupError`` when it is absent."""
    summary = snapshot_summaries(session, (snapshot_id,)).get(snapshot_id)
    if summary is None:
        raise LookupError("Snapshot not found")
    return summary


# =====================================================================
# Offline storage helpers
# Only private experiment tables belong in this local development store.
# Queue ownership must work across both spawned workers and API processes.
# =====================================================================

@lru_cache(maxsize=4)
def local_composition_engine(path):
    """Initialize private SQLite tables once per process, without creating app tables."""
    from sqlalchemy import create_engine, event
    from sqlalchemy.engine import URL
    from sqlalchemy.schema import CreateTable
    from db.models import COMPOSITION_MODELS

    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        URL.create("sqlite", database=str(path)), connect_args={"timeout": 30}
    )

    @event.listens_for(engine, "connect")
    def configure_connection(connection, record):
        """Enforce snapshot references and allow simultaneous polling and progress writes."""
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

    # The worker and first history request can initialize concurrently. Let
    # SQLite decide atomically instead of racing a separate existence query.
    with engine.begin() as connection:
        for model in COMPOSITION_MODELS:
            connection.execute(CreateTable(model.__table__, if_not_exists=True))
    return engine


@contextmanager
def local_queue_owner(store_path):
    """Hold an OS-released lock so a second local backend cannot recover live jobs."""
    if store_path is None:
        yield True
        return
    path = store_path.with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            lock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            unlock = lambda: msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            lock = lambda: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(handle, fcntl.LOCK_UN)
        try:
            lock()
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            unlock()


# =====================================================================
# Frozen source I/O helpers
# Cache only compact immutable catalogs; expand the requested sample later.
# Atomic replacement prevents readers from accepting a partially written file.
# =====================================================================


@lru_cache(maxsize=1)
def read_frozen_source(path, modified_ns, size):
    """Validate and hash a file revision; stat fields invalidate cached replacements."""
    from .models import FrozenSource

    payload = path.read_bytes()
    source = FrozenSource.model_validate_json(payload)
    return source, hashlib.sha256(payload).hexdigest()


def write_frozen_source(destination, source):
    """Write normal JSON with one catalog or board entry per line for Git review."""
    import tempfile

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent, delete=False
        ) as handle:
            temporary = handle.name
            handle.write("{\n")
            fields = type(source).model_fields
            for field_index, name in enumerate(fields):
                handle.write(json.dumps(name) + ":")
                value = getattr(source, name)
                if isinstance(value, tuple):
                    handle.write("[\n")
                    for index, entry in enumerate(value):
                        item = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry
                        handle.write(json.dumps(item, separators=(",", ":"), allow_nan=False))
                        handle.write(",\n" if index + 1 < len(value) else "\n")
                    handle.write("]")
                else:
                    handle.write(json.dumps(value, allow_nan=False))
                handle.write(",\n" if field_index + 1 < len(fields) else "\n")
            handle.write("}\n")
        os.replace(temporary, destination)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


# ============================================================================
# Composition display
#
# A navigation preview is one representative structure, never a union of patterns
# that could imply an unobserved or invalid board structure.
# ============================================================================


def family_preview(family):
    """Project the first representative structure's first six ordered units/traits."""
    from .models import FamilyPatternPreview

    if not family.defining_patterns:
        return None
    first = family.defining_patterns[0]
    units = first.units[:6]
    traits = first.traits[:6 - len(units)]
    if not units and not traits:
        return None
    return FamilyPatternPreview(
        pattern=first.model_copy(update={"units": units, "traits": traits}),
        omitted_requirements=len(first.units) + len(first.traits) - len(units) - len(traits),
        alternative_patterns=len(family.defining_patterns) - 1,
    )


def population_context(run, population_kind):
    """Label a saved run's snapshot context with the displayed population and model."""
    return run.context.model_copy(
        update={
            "population_kind": population_kind,
            "algorithm_id": run.algorithm_id,
            "algorithm_version": run.algorithm_version,
            "experiment_id": run.experiment_id,
        }
    )


def board_example(boards, observation_id, assignment, is_representative):
    """Validate one indexed frozen board and its outcome into a display example.

    Args:
        boards: ``frozen_boards`` index of serialized boards and outcomes.
        observation_id: Board to project; it must exist in the index.
        assignment: The board's saved assignment in the displayed population.
        is_representative: Whether any family lists the board as a representative.
    """
    from domain.compositions.models import BoardObservation, BoardOutcome
    from .models import BoardExampleView

    board, outcome = boards[observation_id]
    return BoardExampleView(
        board=BoardObservation.model_validate_json(board),
        outcome=BoardOutcome.model_validate_json(outcome) if outcome else None,
        assignment=assignment,
        is_representative=is_representative,
    )


def population_boards(snapshot_id, observation_ids):
    """List a population's serialized boards in frozen snapshot order for comparison."""
    from .persistence import frozen_boards

    return [
        board for observation_id, (board, _) in frozen_boards(snapshot_id).items()
        if observation_id in observation_ids
    ]
