"""Exercise typed task execution through the real HTTP/service/runtime boundary."""
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.assistants import router
from domain.tasks.models import KeyMomentsOutput
from domain.tasks import utils


@pytest.fixture
def source():
    """Provide fractional timing, overlapping context, and a silence gap."""
    return {"schema_version": 1, "source": {"transcription_task_id": "speech", "title": "Example", "language": "en"}, "time_unit": "seconds", "time_origin": "media_start", "segments": [
        {"id": "s000000", "start": 12.25, "end": 17.8, "text": "I might spend."},
        {"id": "s000001", "start": 17.5, "end": 22.4, "text": "But I need money later."},
        {"id": "s000002", "start": 90.5, "end": 92.5, "text": "Correction, I will wait."},
    ]}


@pytest.fixture
def client():
    """Use the real task router without unrelated app services or model requests."""
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield client


def test_typed_runtime_and_multiple_ranges(client, source, monkeypatch):
    """Use configured model and denied resources, retaining chronological evidence."""
    def fake(agent, *, input, context, **kwargs):
        """Inspect the SDK invocation and return structured output only."""
        assert agent.output_type is KeyMomentsOutput
        assert agent.spec.model is None
        assert agent.tools == agent.handoffs == []
        assert not agent.spec.repository_context
        assert agent.spec.skill_names == agent.spec.playbook_names == ()
        assert context.runtime.surface == "task"
        return SimpleNamespace(final_output=KeyMomentsOutput.model_validate({"moments": [{"title": "Waiting", "explanation": "The speaker corrects the spending plan.", "evidence": [{"start_segment_id": "s000002", "end_segment_id": "s000002"}, {"start_segment_id": "s000000", "end_segment_id": "s000001"}]}]}))
    monkeypatch.setattr("domain.runtime.execution.Runner.run_sync", fake)
    result = client.post("/api/assistants/tasks/find_key_moments/run", json={"input": json.dumps(source)}).json()
    assert result["ok"] is True
    assert result["result"]["moments"][0]["evidence"][0]["start_segment_id"] == "s000000"


@pytest.mark.parametrize("change", [
    lambda s: s.update(schema_version=2), lambda s: s.update(time_origin="source_start"),
    lambda s: s["segments"][0].update(start=-1), lambda s: s["segments"][0].update(end=1),
    lambda s: s["segments"][1].update(id="s000000"), lambda s: s["segments"][1].update(start=0),
    lambda s: s["segments"][0].update(end=float("inf")),
])
def test_invalid_source_never_calls_sdk(client, source, change, monkeypatch):
    """Reject malformed sources before the SDK boundary."""
    change(source)
    monkeypatch.setattr("domain.runtime.execution.Runner.run_sync", lambda *a, **k: pytest.fail("SDK called"))
    assert not client.post("/api/assistants/tasks/find_key_moments/run", json={"input": json.dumps(source)}).json()["ok"]


@pytest.mark.parametrize("first,last", [("missing", "s000000"), ("s000002", "s000000")])
def test_invalid_reference_fails_whole_task(client, source, monkeypatch, first, last):
    """Never silently drop unsupported or reversed evidence."""
    output = KeyMomentsOutput.model_validate({"moments": [{"title": "Decision", "explanation": "Reason", "evidence": [{"start_segment_id": first, "end_segment_id": last}]}]})
    monkeypatch.setattr("domain.runtime.execution.Runner.run_sync", lambda *a, **k: SimpleNamespace(final_output=output))
    assert not client.post("/api/assistants/tasks/find_key_moments/run", json={"input": json.dumps(source)}).json()["ok"]


@pytest.mark.parametrize("output,ok", [(KeyMomentsOutput(moments=[]), True), (None, False), ("Refusal", False)])
def test_empty_moments_and_missing_structured_output(client, source, monkeypatch, output, ok):
    """Distinguish legitimate abstention from refusal or untyped text."""
    monkeypatch.setattr("domain.runtime.execution.Runner.run_sync", lambda *a, **k: SimpleNamespace(final_output=output))
    assert client.post("/api/assistants/tasks/find_key_moments/run", json={"input": json.dumps(source)}).json()["ok"] is ok


def test_budget_rejected_without_sdk(client, source, monkeypatch):
    """Enforce the named application budget before model work."""
    monkeypatch.setattr(utils, "MAX_INPUT_TOKENS", 5)
    monkeypatch.setattr("domain.runtime.execution.Runner.run_sync", lambda *a, **k: pytest.fail("SDK called"))
    assert "64,000" in client.post("/api/assistants/tasks/find_key_moments/run", json={"input": json.dumps(source)}).json()["error"]
