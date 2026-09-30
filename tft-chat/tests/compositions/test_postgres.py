"""Integration checks restricted to the complete isolated RDS_TEST target."""

import os
import time
from uuid import uuid4
import pytest
from sqlalchemy import select, func
from db.session import open_db
from db.models import (
    CompositionExperiment,
    CompositionSnapshot,
    AnalysisScope,
    AnalysisFactBuild,
    AnalysisBoard,
    AnalysisBoardUnit,
    AnalysisBoardItem,
    AnalysisBoardTrait,
    ANALYSIS_FACT_SCHEMA_VERSION,
)
from services.compositions import persistence, source, display
from services.compositions.worker import CompositionWorker
from services.compositions.models import ExperimentRequest
from domain.compositions.fixtures import fixture_boards, fixture_outcomes


def wait_terminal(experiment_id, timeout=30):
    """Wait for a saved worker terminal state with a short bounded poll interval."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = persistence.get_experiment(experiment_id)
        if run.status not in ("queued", "running"):
            return run
        time.sleep(0.1)
    raise AssertionError("Worker failed to reach terminal state")


@pytest.fixture
def isolated_store(clean_db, monkeypatch):
    """Route coordinator reads/writes only to the repository's isolated test target."""
    for module in (persistence, source):
        monkeypatch.setattr(module, "open_db", lambda: open_db(purpose="test"))
    yield


def seed_ready_facts():
    """Insert a small anonymous ready population with no raw/player identifiers."""
    with open_db(purpose="test") as session:
        scope = AnalysisScope(
            patch="fixture",
            queue_id=1100,
            tft_set_number=17,
            is_active=True,
            status="ready",
            universe_boards=24,
        )
        session.add(scope)
        session.flush()
        session.add(
            AnalysisFactBuild(
                scope_id=scope.scope_id,
                schema_version=ANALYSIS_FACT_SCHEMA_VERSION,
                status="ready",
                board_count=24,
            )
        )
        for board, outcome in zip(fixture_boards(), fixture_outcomes()):
            key = str(uuid4())
            session.add(
                AnalysisBoard(
                    scope_id=scope.scope_id,
                    board_key=key,
                    lobby_key=str(uuid4()),
                    placement=outcome.placement,
                    level=board.level,
                    region="fixture",
                    game_length=1000,
                    unit_count=len(board.units),
                    completed_item_count=sum(len(u.items) for u in board.units),
                )
            )
            session.flush()
            for unit in board.units:
                session.add(
                    AnalysisBoardUnit(
                        scope_id=scope.scope_id,
                        board_key=key,
                        unit_idx=unit.occurrence_index,
                        unit_name=unit.unit.name,
                        star_level=unit.star_level,
                        completed_item_count=len(unit.items),
                        loadout_key="fixture",
                    )
                )
                session.flush()
                for item in unit.items:
                    session.add(
                        AnalysisBoardItem(
                            scope_id=scope.scope_id,
                            board_key=key,
                            unit_idx=unit.occurrence_index,
                            item_slot=item.slot,
                            item_api_name=item.item.key,
                            item_name=item.item.name,
                        )
                    )
            for trait in board.traits:
                session.add(
                    AnalysisBoardTrait(
                        scope_id=scope.scope_id,
                        board_key=key,
                        trait_name=trait.trait.name,
                        num_units=trait.num_units,
                        tier_current=trait.tier_current,
                        style=trait.style,
                    )
                )
        session.commit()


def test_active_source_snapshot_and_unchanged_analytics(isolated_store):
    """Capture occurrence facts reproducibly without modifying published source state."""
    seed_ready_facts()
    request = ExperimentRequest(
        algorithm_id="hdbscan", sample_size=12, full_population=True
    )
    left, right = source.capture_source(request), source.capture_source(request)
    assert left == right
    assert len(left.boards) == 24 and len(left.sample_ids) == 12
    assert all(b.observation_id.startswith("observation-") for b in left.boards)
    assert all(
        t.tier_current is None
        for b in left.boards
        for t in b.traits
        if t.trait.name == "Unreported trait"
    )
    with open_db(purpose="test") as session:
        assert session.scalar(select(func.count()).select_from(AnalysisBoard)) == 24
        assert session.scalar(select(AnalysisScope.status)) == "ready"
        assert session.scalar(select(AnalysisFactBuild.status)) == "ready"
        keys = set(session.scalars(select(AnalysisBoard.board_key)))
    assert all(key not in left.model_dump_json() for key in keys)


@pytest.mark.timeout(90)
def test_owned_process_queue_restart_failure_and_cancellation(isolated_store):
    """Run actual child interpreters, recover interrupted work, and retain immutable results."""
    supervisor = CompositionWorker(purpose="test")
    first = persistence.create_experiment(
        ExperimentRequest(
            algorithm_id="hdbscan", source_kind="fixture", full_population=True
        )
    )
    cancelled = persistence.rerun_experiment(first.experiment_id)
    persistence.cancel_experiment(cancelled.experiment_id)
    supervisor.start()
    try:
        completed = wait_terminal(first.experiment_id)
        assert completed.status == "completed", completed.error
        assert len(completed.result.populations) == 2
        saved = completed.result
        assert persistence.cancel_experiment(first.experiment_id).result == saved
    finally:
        supervisor.close()
    # Persisted state is independent of the first supervisor instance.
    rerun = persistence.rerun_experiment(first.experiment_id)
    with open_db(purpose="test") as session:
        failed = CompositionExperiment(
            experiment_id=str(uuid4()),
            snapshot_id=first.snapshot_id,
            status="queued",
            stage="queued",
            elapsed_seconds=0,
            request={
                **first.request.model_dump(mode="json"),
                "algorithm_id": "missing-adapter",
            },
        )
        interrupted = CompositionExperiment(
            experiment_id=str(uuid4()),
            snapshot_id=first.snapshot_id,
            status="running",
            stage="fitting",
            elapsed_seconds=1,
            request=first.request.model_dump(mode="json"),
        )
        session.add_all([failed, interrupted])
        session.commit()
        failed_id, interrupted_id = failed.experiment_id, interrupted.experiment_id
    supervisor = CompositionWorker(purpose="test")
    supervisor.start()
    try:
        replay = wait_terminal(rerun.experiment_id)
        assert replay.status == "completed", replay.error
        assert replay.result == saved
        assert wait_terminal(failed_id).status == "failed"
        assert persistence.get_experiment(interrupted_id).status == "interrupted"
        assert persistence.get_experiment(cancelled.experiment_id).status == "cancelled"
        comparison = display.compare_experiments(
            first.experiment_id, rerun.experiment_id, "discovery_sample"
        )
        assert comparison.assignment_overlap == 1
    finally:
        supervisor.close()


@pytest.mark.timeout(120)
def test_hdbscan_persists_saved_snapshot_and_population(isolated_store):
    """Run the only production adapter in a real worker on a saved snapshot."""
    first = persistence.create_experiment(
        ExperimentRequest(
            algorithm_id="hdbscan", source_kind="fixture", full_population=True
        )
    )
    runs = [first]
    supervisor = CompositionWorker(purpose="test")
    supervisor.start()
    try:
        for run in runs:
            completed = wait_terminal(run.experiment_id, timeout=60)
            assert completed.status == "completed", (
                run.request.algorithm_id,
                completed.error,
            )
            assert completed.snapshot_id == first.snapshot_id
            assert len(completed.result.populations) == 2
            assert all(len(p.assignments) == 24 for p in completed.result.populations)
            listing = display.composition_list(run.experiment_id, "full_population")
            assert listing.context.algorithm_id == run.request.algorithm_id
            for family in listing.families:
                detail = display.composition_detail(
                    run.experiment_id, "full_population", family.family_id
                )
                assert detail.family.family_id == family.family_id
            for assignment in completed.result.populations[0].assignments:
                assert (
                    display.inspect_board(
                        run.experiment_id, "discovery_sample", assignment.observation_id
                    ).assignment
                    == assignment
                )
        assert display.compare_experiments(
            runs[0].experiment_id, runs[0].experiment_id, "full_population"
        ).identical_population
        active = persistence.rerun_experiment(first.experiment_id)
        deadline = time.monotonic() + 10
        while (
            persistence.get_experiment(active.experiment_id).status == "queued"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        persistence.cancel_experiment(active.experiment_id)
        assert wait_terminal(active.experiment_id).status == "cancelled"
    finally:
        supervisor.close()
