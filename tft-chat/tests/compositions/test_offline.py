"""Portable source integrity and database-free experiment persistence."""

from contextlib import contextmanager
from types import SimpleNamespace
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect

from domain.compositions.fixtures import fixture_boards, fixture_outcomes
from services.compositions import source, snapshot, storage, persistence, worker, display
from services.compositions.models import ExperimentRequest, FrozenSource
from services.compositions.utils import local_composition_engine, local_queue_owner, read_frozen_source


@pytest.fixture
def frozen_population(tmp_path, monkeypatch):
    """Export real contract fixtures through the same encoder as the live population."""
    boards, outcomes = fixture_boards(), fixture_outcomes()
    keys = [f"private-board-{index}" for index in range(len(boards))]

    @contextmanager
    def active():
        """Provide metadata without allowing export to consult application credentials."""
        yield None, SimpleNamespace(patch="offline-test", tft_set_number=17, queue_id=1100), keys

    monkeypatch.setattr(source, "active_source", active)
    monkeypatch.setattr(source, "read_fact_boards", lambda *args: zip(keys, boards, outcomes))
    path = tmp_path / "eligible-boards.json"
    exported = source.export_frozen_source(path)
    monkeypatch.setattr(snapshot, "frozen_source_path", lambda: path)
    yield path, exported
    read_frozen_source.cache_clear()


@pytest.fixture
def offline_store(frozen_population, tmp_path, monkeypatch):
    """Fail any RDS access and use only a disposable private offline store."""
    monkeypatch.setattr(storage, "load_config", lambda: SimpleNamespace(chat=SimpleNamespace(composition_offline=True)))
    path = tmp_path / "offline_test.db"
    monkeypatch.setattr(storage, "local_store_path", lambda: path)

    def no_database(*args, **kwargs):
        """Reject accidental online routing while exercising the entire offline lifecycle."""
        raise AssertionError("Application database must not be used")

    monkeypatch.setattr(storage, "open_application_db", no_database)
    monkeypatch.setattr(source, "open_db", no_database)
    yield path
    local_composition_engine(path).dispose()
    local_composition_engine.cache_clear()


def test_export_round_trip_preserves_all_occurrences_and_outcomes(frozen_population):
    """Catalog encoding loses neither duplicates, slot ownership, nor unknown traits."""
    path, exported = frozen_population
    payload = path.read_text()
    assert "private-board-" not in payload
    assert FrozenSource.model_validate_json(payload) == exported
    request = ExperimentRequest(algorithm_id="hdbscan", full_population=True, sample_size=12)
    captured = snapshot.capture_frozen_source(request)
    assert captured.eligible_boards == len(fixture_boards())
    for actual, expected in zip(captured.boards, fixture_boards()):
        assert actual.model_dump(exclude={"observation_id"}) == expected.model_dump(exclude={"observation_id"})
    assert [o.placement for o in captured.outcomes] == [o.placement for o in fixture_outcomes()]
    assert snapshot.capture_frozen_source(request) == captured
    sampled = snapshot.capture_frozen_source(request.model_copy(update={"full_population": False}))
    full_sample = [b for b in captured.boards if b.observation_id in captured.sample_ids]
    assert [b.units for b in sampled.boards] == [b.units for b in full_sample]
    assert sampled.eligible_boards == captured.eligible_boards
    assert len(sampled.boards) == 12


@pytest.mark.parametrize("damage", ["truncated", "catalog", "duplicate", "unknown", "version"])
def test_export_validation_rejects_corruption(frozen_population, damage):
    """Refuse partial populations, bad references, and accidental private fields."""
    path, _ = frozen_population
    value = json.loads(path.read_text())
    if damage == "truncated":
        value["placements"].pop()
    elif damage == "catalog":
        value["boards"][0]["units"][0] = len(value["units"])
    elif damage == "duplicate":
        value["boards"][0]["units"].append(value["boards"][0]["units"][0])
    elif damage == "unknown":
        value["scope_id"] = "private"
    else:
        value["schema_version"] = "future"
    with pytest.raises(ValidationError):
        FrozenSource.model_validate(value)
    path.write_text(json.dumps(value))
    assert not snapshot.frozen_source_summary().ready


def test_offline_history_execution_comparison_and_cancellation(offline_store, monkeypatch):
    """Run, reopen, compare, and cancel experiments with every RDS entry point blocked."""
    assert source.source_summary("active").ready
    assert "Offline development" in source.source_summary("active").warning
    monkeypatch.setattr(worker, "watch_parent", lambda parent_pid: None)
    run = persistence.create_experiment(ExperimentRequest(
        algorithm_id="hdbscan", sample_size=12, full_population=True,
    ))
    supervisor = worker.CompositionWorker()
    assert supervisor.claim() == run.experiment_id
    worker.execute_run(run.experiment_id, 0)
    completed = persistence.get_experiment(run.experiment_id)
    assert completed.status == "completed", completed.error
    assert len(completed.result.populations) == 2
    assert display.composition_list(run.experiment_id, "full_population").context.patch == "offline-test"
    local_composition_engine(offline_store).dispose()
    rerun = persistence.rerun_experiment(run.experiment_id)
    assert rerun.snapshot_id == run.snapshot_id
    assert supervisor.claim() == rerun.experiment_id
    worker.execute_run(rerun.experiment_id, 0)
    comparison = display.compare_experiments(run.experiment_id, rerun.experiment_id, "discovery_sample")
    assert comparison.identical_population
    cancelled = persistence.rerun_experiment(run.experiment_id)
    assert persistence.cancel_experiment(cancelled.experiment_id).status == "cancelled"
    assert persistence.cancel_experiment(run.experiment_id).result == completed.result
    assert len(persistence.history().experiments) == 3
    assert set(inspect(local_composition_engine(offline_store)).get_table_names()) == {
        "composition_snapshots", "composition_snapshot_summaries", "composition_experiments"
    }


def test_offline_lock_excludes_second_supervisor(offline_store):
    """A second backend cannot mark another local supervisor's running jobs interrupted."""
    with local_queue_owner(offline_store) as first:
        assert first
        with local_queue_owner(offline_store) as second:
            assert not second
    with local_queue_owner(offline_store) as replacement:
        assert replacement


def test_online_and_test_targets_keep_existing_routing(monkeypatch):
    """The development switch cannot redirect isolated tests or general app access."""
    monkeypatch.setattr(storage, "open_application_db", lambda **kwargs: kwargs)
    monkeypatch.setattr(storage, "offline_enabled", lambda: False)
    assert storage.open_db() == {"purpose": "app"}
    monkeypatch.setattr(storage, "offline_enabled", lambda: True)
    assert storage.open_db(purpose="test") == {"purpose": "test"}


def test_missing_source_does_not_fall_back_to_database(offline_store, frozen_population):
    """Offline mode requires its checked-in input even on a database-connected machine."""
    path, _ = frozen_population
    path.unlink()
    assert not source.source_summary("active").ready
    with pytest.raises(FileNotFoundError):
        source.capture_source(ExperimentRequest(algorithm_id="hdbscan"))


@pytest.mark.parametrize("offline, expected", [(True, ["start", "close"]), (False, [])])
def test_api_starts_offline_worker_without_application_database(monkeypatch, offline, expected):
    """Degraded application startup must still own offline composition execution."""
    import asyncio
    import importlib
    from fastapi import FastAPI

    api_app = importlib.import_module("api.app")
    events = []

    class Supervisor:
        """Record lifecycle ownership without launching a thread in this unit test."""

        def start(self):
            """Record the worker start requested by API startup."""
            events.append("start")

        def close(self):
            """Record cleanup when the API lifespan ends."""
            events.append("close")

    monkeypatch.setattr(api_app, "load_config", lambda: SimpleNamespace(chat=SimpleNamespace(
        composition_workbench=True, composition_offline=offline,
    )))
    monkeypatch.setattr(api_app, "_warm_database_at_startup", lambda: {"available": False})
    monkeypatch.setattr(api_app, "_install_local_trace_recorder", lambda: None)
    monkeypatch.setattr(worker, "CompositionWorker", Supervisor)

    async def lifespan():
        """Enter and leave the real API lifespan with an unavailable app target."""
        async with api_app._lifespan(FastAPI()):
            pass

    asyncio.run(lifespan())
    assert events == expected
