"""Native webhook and durable queue behavior without paid model execution."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest

from evals.langfuse.jobs import JobStore
from evals.langfuse.models import ExperimentTrigger, RunConfig
from evals.langfuse.server import ExperimentService, create_app
from domain.assistants.constants import AssistantName


def test_native_payload_and_invalid_settings():
    """The actual pinned server body parses; invalid run controls are rejected."""
    trigger = ExperimentTrigger.model_validate({
        "projectId": "tft-apps-evals", "datasetId": "dataset", "datasetName": f"chattft/{AssistantName.DUMMY_ASSISTANT}",
        "payload": json.dumps({"repetitions": 2}),
    })
    assert trigger.config.repetitions == 2
    selected = ExperimentTrigger.model_validate({
        "datasetName": "chattft/manual-probe",
        "payload": json.dumps({"assistant": AssistantName.UNIT_EXPERT}),
    })
    assert selected.config.assistant == AssistantName.UNIT_EXPERT
    for config in ({"concurrency": 0}, {"concurrency": 5}, {"repetitions": True},
                   {"action": "replay"}, {"variants": [{"name": "x"}, {"name": "x"}]},
                   {"arbitrary_file": "/tmp/code.py"}, {"assistant": 3}):
        with pytest.raises(ValueError):
            RunConfig.model_validate(config)


def test_durable_jobs_mark_interrupted_and_keep_queued(tmp_path):
    """Recovery never silently reruns an operation whose paid calls may have begun."""
    jobs = JobStore(tmp_path)
    first = jobs.submit({"case": "one"}, "snapshot-a")
    second = jobs.submit({"case": "two"}, "snapshot-b")
    assert jobs.claim()["id"] == first
    restarted = JobStore(tmp_path)
    assert restarted.recover() == [first]
    assert restarted.get(first)["state"] == "interrupted"
    assert restarted.claim()["id"] == second
    restarted.finish(second, "failed", error="model timeout")
    assert restarted.get(second)["error"] == "model timeout"
    assert restarted.claim() is None


def test_export_is_terminal_before_consumer_can_claim(tmp_path):
    """A concurrent queue consumer can never observe an export as runnable work."""
    from concurrent.futures import ThreadPoolExecutor
    jobs = JobStore(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        exports = [pool.submit(jobs.submit, {"config": {"action": "export"}}, f"snapshot-{n}", exported=True)
                   for n in range(20)]
        claims = [pool.submit(jobs.claim) for _ in range(20)]
    assert all(future.result() is None for future in claims)
    assert all(jobs.get(future.result())["state"] == "exported" for future in exports)


def test_dead_consumer_makes_health_unavailable(tmp_path):
    """A failed queue claim cannot leave a falsely healthy accepting service."""
    from fastapi import HTTPException
    service = ExperimentService(tmp_path / "snapshots", tmp_path / "runtime", Mock)
    service.jobs.claim = Mock(side_effect=RuntimeError("disk failure"))
    service.consume()
    assert "disk failure" in service.consumer_error
    app = create_app(service=service, token="test")
    health = next(route.endpoint for route in app.routes if route.path == "/health")
    with pytest.raises(HTTPException) as error:
        health()
    assert error.value.status_code == 503


def test_provenance_tracks_untracked_content_and_container_fallback(tmp_path, monkeypatch):
    """Changing a new source file changes provenance before it is Git-tracked."""
    from evals.langfuse import server
    monkeypatch.setattr(server, "__file__", str(tmp_path / "evals" / "langfuse" / "server.py"))
    new_file = tmp_path / "new.py"
    new_file.write_text("first")
    def git_output(command, **kwargs):
        """Supply deterministic Git identity and a single untracked path."""
        return b"revision" if "rev-parse" in command else b"new.py\0" if "ls-files" in command else b""
    monkeypatch.setattr(server.subprocess, "check_output", git_output)
    service = ExperimentService(tmp_path / "snapshots", tmp_path / "runtime", Mock)
    first = service.provenance()
    new_file.write_text("second")
    assert first["working_tree_fingerprint"] != service.provenance()["working_tree_fingerprint"]
    monkeypatch.setattr(server.subprocess, "check_output", Mock(side_effect=OSError("no git")))
    monkeypatch.setenv("CHAT_TFT_GIT_REVISION", "built-revision")
    monkeypatch.setenv("CHAT_TFT_WORKING_TREE_FINGERPRINT", "built-fingerprint")
    assert service.provenance() == {"git_revision": "built-revision", "working_tree_fingerprint": "built-fingerprint"}


def test_http_auth_and_validation_before_submission():
    """Unsigned and malformed UI requests cannot schedule any application work."""
    service = Mock()
    service.submit.return_value = {"job_id": "one", "snapshot": "abc"}
    service.jobs.get.return_value = None
    with TestClient(create_app(service=service, token="private-test-token")) as http:
        assert http.get("/health").status_code == 200
        payload = {"datasetName": f"chattft/{AssistantName.DUMMY_ASSISTANT}", "payload": "{}"}
        assert http.post("/experiments", json=payload).status_code == 401
        headers = {"authorization": "Bearer private-test-token"}
        assert http.post("/experiments", headers=headers, json={**payload, "payload": "not JSON"}).status_code == 422
        service.submit.assert_not_called()
        assert http.post("/experiments", headers=headers, json=payload).status_code == 202
        service.submit.assert_called_once()
        assert http.get("/jobs/missing", headers=headers).status_code == 404


def test_export_and_replay_use_frozen_content(tmp_path, monkeypatch):
    """Export calls no evaluator and later replay reads original immutable inputs."""
    from evals.langfuse import content
    source = Path(__file__).resolve().parents[1] / "snapshots"
    entry = next(e for e in content.load_catalog(source) if e["name"] == AssistantName.DUMMY_ASSISTANT)
    bundle = content.load_snapshot("12919b463fd2b4bd5fdda2765fe6f7745191fcd4668a062576ff8a923f493591", source)
    bundle["dataset_id"] = "dataset"
    remote = deepcopy(bundle)
    remote["config"]["action"] = "export"
    monkeypatch.setattr(content, "fetch_bundle", lambda *args: deepcopy(remote))
    service = ExperimentService(tmp_path / "snapshots", tmp_path / "runtime", Mock)
    service.client = Mock()
    exported = service.submit(ExperimentTrigger(datasetName=f"chattft/{AssistantName.DUMMY_ASSISTANT}", config={"action": "export"}))
    assert service.jobs.get(exported["job_id"])["state"] == "exported"
    remote["items"][0]["input"]["input"] = "later UI edit"
    replay = service.submit(ExperimentTrigger(datasetName=f"chattft/{AssistantName.DUMMY_ASSISTANT}", config={"action": "replay", "snapshot": exported["snapshot"]}))
    job = service.jobs.claim()
    assert job["id"] == replay["job_id"]
    assert job["bundle"]["items"][0]["input"]["input"] == bundle["items"][0]["input"]["input"]
    assert job["bundle"]["config"]["action"] == "run"


def test_slow_preparation_never_schedules_after_webhook_expiry(tmp_path, monkeypatch):
    """A timed-out preparation cannot unexpectedly start paid work after UI failure."""
    from evals.langfuse import content, server
    source = Path(__file__).resolve().parents[1] / "snapshots"
    entry = next(entry for entry in content.load_catalog(source) if entry["name"] == AssistantName.DUMMY_ASSISTANT)
    bundle = content.load_snapshot("12919b463fd2b4bd5fdda2765fe6f7745191fcd4668a062576ff8a923f493591", source)
    bundle["dataset_id"] = "dataset"
    monkeypatch.setattr(content, "fetch_bundle", lambda *args: deepcopy(bundle))
    clock = iter([100.0, 115.0])
    monkeypatch.setattr(server, "perf_counter", lambda: next(clock))
    service = ExperimentService(tmp_path / "snapshots", tmp_path / "runtime", Mock)
    service.client = Mock()
    with pytest.raises(ValueError, match="no evaluation was scheduled"):
        service.submit(ExperimentTrigger(datasetName=f"chattft/{AssistantName.DUMMY_ASSISTANT}"))
    assert service.jobs.claim() is None
    assert not service.wakeup.is_set()
