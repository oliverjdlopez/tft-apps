"""Private-table persistence, source readiness, immutable reruns, and recovery."""

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from db.models import (
    COMPOSITION_MODELS,
    CompositionExperiment,
    CompositionSnapshot,
    AnalysisScope,
    AnalysisFactBuild,
)
from services.compositions import persistence, source, worker
from services.compositions.models import ExperimentRequest, ExperimentResult
from services.compositions.execution import execute_snapshot
from services.compositions.utils import result_view
from scripts.migrate_compositions import migrate


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Use a disposable isolated unit-test database without application targets."""
    engine = create_engine(f"sqlite:///{tmp_path / 'composition_test.db'}")
    migrate(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    for module in (persistence, worker):
        monkeypatch.setattr(module, "open_db", lambda **kwargs: sessions())
    yield sessions
    engine.dispose()


def request(**updates):
    """Build execution-only fixture requests without active database reads."""
    return ExperimentRequest(
        algorithm_id="hdbscan", source_kind="fixture", **updates
    )


def test_restart_rerun_cancellation_and_result_immutability(store):
    """Saved snapshots survive reopen and reruns append records without mutation."""
    run = persistence.create_experiment(request(full_population=True))
    assert run.sample_boards == 24
    supervisor = worker.CompositionWorker()
    assert supervisor.claim() == run.experiment_id
    supervisor.recover()
    assert persistence.get_experiment(run.experiment_id).status == "interrupted"
    rerun = persistence.rerun_experiment(run.experiment_id)
    assert rerun.experiment_id != run.experiment_id
    assert rerun.snapshot_id == run.snapshot_id
    snapshot = persistence.get_snapshot(run.snapshot_id)
    result = execute_snapshot(snapshot, rerun.request)
    with store() as session:
        row = session.get(CompositionExperiment, rerun.experiment_id)
        row.status, row.stage, row.result = (
            "completed",
            "completed",
            result.model_dump(mode="json"),
        )
        session.commit()
    cancelled = persistence.cancel_experiment(rerun.experiment_id)
    assert cancelled.status == "completed"
    assert cancelled.result == result_view(result.model_dump(mode="json"))
    queued = persistence.rerun_experiment(run.experiment_id)
    assert persistence.cancel_experiment(queued.experiment_id).status == "cancelled"
    assert supervisor.claim() is None
    assert len(persistence.history().experiments) == 3
    with store() as session:
        assert len(session.scalars(select(CompositionSnapshot)).all()) == 1


def test_run_views_use_summaries_and_omit_heavy_result_fields(store):
    """History backfills older snapshots; views and display skip frozen state."""
    from db.models import CompositionSnapshotSummary
    from services.compositions import display

    run = persistence.create_experiment(request(full_population=True))
    snapshot = persistence.get_snapshot(run.snapshot_id)
    result = execute_snapshot(snapshot, run.request)
    with store() as session:
        # Simulate a snapshot saved before summaries existed.
        session.delete(session.get(CompositionSnapshotSummary, run.snapshot_id))
        row = session.get(CompositionExperiment, run.experiment_id)
        row.status, row.stage = "completed", "completed"
        row.result = result.model_dump(mode="json")
        session.commit()
    [saved] = persistence.history().experiments
    assert (saved.eligible_boards, saved.sample_boards) == (24, 24)
    assert saved.context == snapshot.context
    with store() as session:
        assert session.get(CompositionSnapshotSummary, run.snapshot_id) is not None
    reopened = persistence.get_experiment(run.experiment_id).result.model_dump()
    assert "state" not in reopened["model"]
    assert "discovery_assignments" not in reopened
    assert "candidates" not in reopened["populations"][0]["assignments"][0]
    family = result.model.families[0].family_id
    detail = display.composition_detail(run.experiment_id, "full_population", family)
    assert {e.board for e in detail.examples} <= set(snapshot.boards)
    observation = result.populations[0].assignments[0].observation_id
    board = display.inspect_board(run.experiment_id, "discovery_sample", observation)
    assert board.assignment == result.populations[0].assignments[0]


def test_explicit_refresh_required_for_changed_sampling(store):
    """Saved input reuse never silently substitutes a new population."""
    run = persistence.create_experiment(request(sample_size=12))
    with pytest.raises(ValueError, match="Refresh source"):
        persistence.create_experiment(run.request.model_copy(update={"seed": 1}))
    with pytest.raises(ValueError, match="input source requires Refresh source"):
        persistence.create_experiment(
            run.request.model_copy(update={"source_kind": "active"})
        )
    with pytest.raises(ValueError, match="no full population"):
        persistence.create_experiment(
            run.request.model_copy(update={"full_population": True})
        )
    refreshed = persistence.create_experiment(
        run.request.model_copy(update={"snapshot_id": None, "seed": 1})
    )
    assert refreshed.snapshot_id != run.snapshot_id


def test_large_requested_sample_caps_at_population_and_reruns(store):
    """Accept large requests while freezing no more than the actual source boards."""
    run = persistence.create_experiment(request(sample_size=20001))
    assert run.sample_boards == run.eligible_boards == 24
    assert run.request.sample_size == 20001
    rerun = persistence.rerun_experiment(run.experiment_id)
    assert rerun.snapshot_id == run.snapshot_id
    assert rerun.sample_boards == 24


def test_snapshot_samples_more_than_two_thousand_boards():
    """The capture helper samples above the old cap without needing a large fit."""
    from domain.compositions.fixtures import fixture_boards
    from services.compositions.utils import make_snapshot

    template = fixture_boards()[0]
    boards = tuple(
        template.model_copy(update={"observation_id": f"board-{index}"})
        for index in range(2500)
    )
    snapshot = make_snapshot(request(sample_size=2200), boards, (), "test", 17, 1100)
    assert len(snapshot.sample_ids) == len(snapshot.boards) == 2200
    assert snapshot.eligible_boards == 2500


def test_source_unavailable_does_not_fall_back_to_raw(tmp_path, monkeypatch):
    """A missing or dirty scope refuses discovery without querying raw rows."""
    engine = create_engine(f"sqlite:///{tmp_path / 'unavailable_test.db'}")
    AnalysisScope.__table__.create(engine)
    AnalysisFactBuild.__table__.create(engine)
    sessions = sessionmaker(engine)
    monkeypatch.setattr(source, "open_db", sessions)
    with pytest.raises(ValueError, match="unavailable or not ready"):
        source.capture_source(ExperimentRequest(algorithm_id="hdbscan"))
    engine.dispose()


def test_empty_results_keep_null_denominators(store):
    """Empty inputs produce saved usable results without fabricated zero outcomes."""
    from services.compositions.utils import make_snapshot

    snapshot = make_snapshot(request(), (), (), "fixture", 17, 1100)
    result = execute_snapshot(snapshot, request())
    assert result.model.families == ()
    assert result.populations[0].coverage is None
    assert result.populations[0].assignments == ()


def test_migration_is_additive_idempotent_and_registered(store):
    """Private tables are runtime-registered but never become published projections."""
    from db.models import RUNTIME_MODELS, QUERY_TABLE_MODELS, TABLE_MODELS

    with store() as session:
        migrate(session.bind)
    assert all(model in RUNTIME_MODELS for model in COMPOSITION_MODELS)
    assert all(model not in QUERY_TABLE_MODELS for model in COMPOSITION_MODELS)
    assert all(model.__tablename__ not in TABLE_MODELS for model in COMPOSITION_MODELS)


def test_saved_version_changes_require_explicit_new_selection(store):
    """A rerun must not silently execute a different implementation revision."""
    run = persistence.create_experiment(request())
    with pytest.raises(ValueError, match="Saved algorithm version"):
        persistence.create_experiment(
            run.request.model_copy(update={"algorithm_version": "future"})
        )


def test_removed_algorithm_runs_are_hidden_without_deleting_rows(store):
    """Legacy method runs remain stored but are absent from every run workspace path."""
    from services.compositions.persistence import saved_result

    current = persistence.create_experiment(request())
    with store() as session:
        legacy = CompositionExperiment(
            experiment_id="legacy-hierarchical",
            snapshot_id=current.snapshot_id,
            request={**current.request.model_dump(mode="json"), "algorithm_id": "hierarchical"},
            status="queued",
            stage="queued",
            elapsed_seconds=0,
        )
        session.add(legacy)
        session.commit()

    assert [run.experiment_id for run in persistence.history().experiments] == [current.experiment_id]
    for operation in (
        lambda: persistence.get_experiment("legacy-hierarchical"),
        lambda: persistence.cancel_experiment("legacy-hierarchical"),
        lambda: persistence.rerun_experiment("legacy-hierarchical"),
        lambda: saved_result("legacy-hierarchical"),
    ):
        with pytest.raises(LookupError, match="Experiment not found"):
            operation()
    with store() as session:
        assert session.get(CompositionExperiment, "legacy-hierarchical") is not None


def test_only_hdbscan_is_registered_and_other_requests_are_rejected():
    """The API catalog contract and request validator expose only HDBSCAN."""
    from domain.compositions.registry import ALGORITHM_IDS, get_adapter

    assert ALGORITHM_IDS == ("hdbscan",)
    assert get_adapter("hdbscan").algorithm_id == "hdbscan"
    with pytest.raises(ValueError, match="Unknown composition algorithm"):
        get_adapter("hierarchical")


def test_source_summary_contains_safe_readiness(monkeypatch):
    """Unavailable infrastructure yields a safe summary while fixtures stay ready."""

    def unavailable():
        """Simulate a credential-bearing database failure without exposing its text."""
        raise RuntimeError("private-secret-connection")

    monkeypatch.setattr(source, "open_db", unavailable)
    active = source.source_summary("active")
    assert not active.ready and active.eligible_boards is None
    assert "private-secret" not in active.model_dump_json()
    assert source.source_summary("fixture").eligible_boards == 24


def test_worker_launch_failure_is_terminal_and_queue_can_continue(store, monkeypatch):
    """A spawn failure must not leave a permanently running queue entry."""
    from types import SimpleNamespace

    class BrokenProcess:
        """Simulate an OS refusing child creation before a process exists."""

        def start(self):
            """Raise the failure handled by the supervisor's spawn boundary."""
            raise OSError("process limit")

    monkeypatch.setattr(
        worker.multiprocessing,
        "get_context",
        lambda method: SimpleNamespace(Process=lambda **kwargs: BrokenProcess()),
    )
    run = persistence.create_experiment(request())
    supervisor = worker.CompositionWorker()
    assert supervisor.claim() == run.experiment_id
    supervisor.supervise(run.experiment_id)
    failed = persistence.get_experiment(run.experiment_id)
    assert failed.status == "failed" and failed.result is None
    assert "could not start" in failed.error
    next_run = persistence.rerun_experiment(run.experiment_id)
    assert supervisor.claim() == next_run.experiment_id
