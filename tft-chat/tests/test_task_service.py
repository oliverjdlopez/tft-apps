"""Verify transcript distillation through the normal task and CLI runtime."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.tasks import transcript
from domain.assistants import assistant_spec
from domain.assistants.constants import AssistantName
from domain.assistants.utils import wrap_task_input
from services import task_service


@pytest.mark.parametrize("original", [
    'Source: guide, section Economy. At 30 gold I usually save, unless weak.',
    '{"id": 1, "start": 12, "text": "I might roll"}\n{"id": 2, "text": "only if weak"}',
])
def test_transcription_pipeline_distills_original_source_once(monkeypatch, original) -> None:
    """Send plain text and segmented transcripts unchanged to one isolated agent."""
    calls = []
    output = "# Economy reference\n\n## Reference notes\n- Conditional advice."

    async def fake_run(agent, *, input, context, hooks, **kwargs):
        """Inspect the real prepared invocation without executing a model."""
        from domain.runtime import AssistantRunContext
        assert isinstance(context, AssistantRunContext)
        assert callable(agent.instructions)
        assert context.runtime.surface == "task"
        assert context.resources.references == ()
        assert context.resources.skills == ()
        assert agent.tools == []
        assert agent.handoffs == []
        assert agent.output_type is None
        calls.append((agent.name, input))
        return SimpleNamespace(final_output=output)

    monkeypatch.setattr("domain.assistants.assistant.Runner.run", fake_run)
    assert transcript.run_transcription_pipeline(original) == output
    assert calls == [
        (AssistantName.DISTILL_TRANSCRIPT, wrap_task_input(
            original, assistant_spec(AssistantName.DISTILL_TRANSCRIPT).task_prompt,
        )),
    ]


def test_task_service_exposes_the_same_catalog_and_response_contract(monkeypatch) -> None:
    """Keep existing task clients compatible with the single-stage replacement."""
    monkeypatch.setattr(
        task_service, "run_transcription_pipeline",
        lambda input_text: f"distilled: {input_text}",
    )
    assert task_service.task_catalog() == {"tasks": [{
        "name": "transcription_pipeline",
        "description": "Distill transcripts or other text into source-grounded ChatTFT references.",
    }]}
    assert task_service.run_task("transcription_pipeline", input_text="sample") == {
        "ok": True, "task": "transcription_pipeline", "result": "distilled: sample",
    }
    with pytest.raises(LookupError, match="Unknown task: missing"):
        task_service.run_task("missing")


def test_distillation_failure_uses_existing_task_error_contract(monkeypatch) -> None:
    """Surface failed distillation instead of reporting undistilled input as success."""
    async def fail(*args, **kwargs):
        """Fail at the SDK boundary without external requests."""
        raise RuntimeError("distillation failed")

    monkeypatch.setattr("domain.assistants.assistant.Runner.run", fail)
    assert task_service.run_task("transcription_pipeline", input_text="source") == {
        "ok": False, "task": "transcription_pipeline",
        "error": "RuntimeError: distillation failed",
    }


def test_media_distillation_task_http_route_runs_the_registered_assistant(monkeypatch) -> None:
    """Exercise the Media request's real route, task, and runtime without a model."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.routes.assistants import router

    app = FastAPI()
    app.include_router(router)
    source = 'Source metadata:\n{"name": "Transcript.txt"}\n\nSource text:\n[00:12] Conditional advice.'
    calls = []

    async def fake_run(agent, *, input, context, **kwargs):
        """Capture the model boundary reached by the normal task endpoint."""
        calls.append((agent.name, input))
        assert context.resources.references == ()
        assert context.resources.skills == ()
        return SimpleNamespace(final_output="# Distilled reference\n\nSource-grounded notes.")

    monkeypatch.setattr("domain.assistants.assistant.Runner.run", fake_run)
    with TestClient(app) as client:
        response = client.post("/api/assistants/tasks/transcription_pipeline/run", json={"input": source})
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "task": "transcription_pipeline",
        "result": "# Distilled reference\n\nSource-grounded notes.",
    }
    assert calls == [(AssistantName.DISTILL_TRANSCRIPT, wrap_task_input(
        source, assistant_spec(AssistantName.DISTILL_TRANSCRIPT).task_prompt,
    ))]


@pytest.mark.parametrize("explicit", [False, True])
def test_assistant_cli_distills_file_with_default_or_explicit_name(monkeypatch, tmp_path, capsys, explicit) -> None:
    """Exercise the script entry point with the requested assistant identity."""
    from domain.assistants.__main__ import main
    source = tmp_path / "source.txt"
    source.write_text("[00:12] Supplied source", encoding="utf-8")
    calls = []

    async def fake_run(agent, *, input, context, **kwargs):
        """Observe the CLI's real prepared invocation without a paid model call."""
        calls.append((agent.name, input, context.runtime.surface))
        return SimpleNamespace(final_output="# Distilled reference")

    args = ["assistants"] + (["distill-transcript"] if explicit else [])
    monkeypatch.setattr("sys.argv", args + ["--input-file", str(source)])
    monkeypatch.setattr("domain.assistants.assistant.Runner.run", fake_run)
    main()
    assert calls == [(AssistantName.DISTILL_TRANSCRIPT, wrap_task_input(
        source.read_text(), assistant_spec(AssistantName.DISTILL_TRANSCRIPT).task_prompt,
    ), "cli")]
    assert capsys.readouterr().out == "# Distilled reference\n"
