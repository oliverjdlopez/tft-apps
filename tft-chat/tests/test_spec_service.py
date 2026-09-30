from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.backend.api.app import create_app
from services import spec_service


@pytest.fixture
def spec_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "assistant_specs"
    fixture = root / "fixture"
    fixture.mkdir(parents=True)
    (fixture / "system.md").write_text("# Fixture\n\nOriginal prompt.\n", encoding="utf-8")
    (fixture / "agent.json").write_text(
        json.dumps({"name": "fixture", "description": "Fixture assistant"}, indent=2) + "\n",
        encoding="utf-8",
    )
    (fixture / "notes.md").write_text("not part of the spec\n", encoding="utf-8")
    monkeypatch.setattr(spec_service, "ASSISTANT_SPECS_DIR", root)
    monkeypatch.setattr(spec_service, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        spec_service,
        "load_eval_suites",
        lambda: [SimpleNamespace(name="fixture_eval", assistant="fixture")],
    )
    monkeypatch.setattr(spec_service, "resolve_assistant_tools", lambda _spec: [])
    monkeypatch.setattr(spec_service, "reload_assistant_specs", lambda: None)
    return fixture


def test_spec_workspace_only_exposes_loaded_spec_files(spec_workspace: Path) -> None:
    result = spec_service.workspace()
    assistant = result["assistants"][0]

    assert assistant["name"] == "fixture"
    assert assistant["eval_suites"] == ["fixture_eval"]
    assert [source["label"] for source in assistant["sources"]] == ["agent.json", "system.md"]


def test_spec_document_save_validates_and_detects_conflicts(spec_workspace: Path) -> None:
    source = next(
        source
        for source in spec_service.workspace()["assistants"][0]["sources"]
        if source["label"] == "system.md"
    )
    document = spec_service.read_document(source["document_id"])
    saved = spec_service.save_document(
        document["id"],
        document["content"].replace("Original", "Updated"),
        document["revision"],
    )

    assert "Updated prompt" in saved["content"]
    assert saved["test_suites"] == ["fixture_eval"]
    with pytest.raises(spec_service.DocumentConflictError):
        spec_service.save_document(document["id"], document["content"], document["revision"])

    agent_source = next(
        source
        for source in spec_service.workspace()["assistants"][0]["sources"]
        if source["label"] == "agent.json"
    )
    agent = spec_service.read_document(agent_source["document_id"])
    with pytest.raises(ValueError, match="JSON object"):
        spec_service.save_document(agent["id"], "[]\n", agent["revision"])


def test_spec_routes_delegate_and_report_conflicts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(spec_service, "workspace", lambda: {"assistants": []})
    monkeypatch.setattr(
        spec_service,
        "read_document",
        lambda document_id: {"id": document_id, "content": "prompt", "revision": "a" * 64},
    )

    def conflict(*args: object) -> dict[str, object]:
        raise spec_service.DocumentConflictError("reload first")

    monkeypatch.setattr(spec_service, "save_document", conflict)
    client = TestClient(create_app())

    assert client.get("/api/specs").json() == {"assistants": []}
    assert client.get("/api/specs/documents/doc-1").status_code == 200
    response = client.put(
        "/api/specs/documents/doc-1",
        json={"content": "updated", "revision": "a" * 64},
    )
    assert response.status_code == 409
    assert response.json() == {"detail": "reload first"}
