from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.tasks import transcript
from domain.assistants import assistant_spec
from domain.assistants.utils import wrap_task_input
from services import task_service


def test_transcription_pipeline_runs_the_three_assistants_in_order(monkeypatch) -> None:
    original = '{"id": 1, "text": "um hello"}\n{"id": 2, "text": "world"}'
    calls: list[tuple[str, str]] = []
    outputs = {
        "clean_transcript": '{"edits": [{"id": 1, "text": "hello"}]}',
        "compact_transcript": "compact transcript",
        "analyze_transcript": "analysis",
    }

    async def fake_run(agent, *, input, context, hooks, **kwargs):
        """Observe wrapped input and typed context without model execution."""
        from domain.runtime import AssistantRunContext
        assert isinstance(context, AssistantRunContext)
        assert callable(agent.instructions)
        calls.append((agent.name, input))
        return SimpleNamespace(final_output=outputs[agent.name])

    monkeypatch.setattr("domain.assistants.assistant.Runner.run", fake_run)

    assert transcript.run_transcription_pipeline(original) == "analysis"
    assert calls == [
        ("clean_transcript", wrap_task_input(original, assistant_spec("clean_transcript").task_prompt)),
        (
            "compact_transcript",
            wrap_task_input('{"id": 1, "text": "hello"}\n{"id": 2, "text": "world"}', assistant_spec("compact_transcript").task_prompt),
        ),
        (
            "analyze_transcript",
            wrap_task_input("compact transcript", assistant_spec("analyze_transcript").task_prompt),
        ),
    ]


def test_task_service_exposes_the_same_catalog_and_response_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        task_service,
        "run_transcription_pipeline",
        lambda input_text: f"analyzed: {input_text}",
    )

    assert task_service.task_catalog() == {
        "tasks": [
            {
                "name": "transcription_pipeline",
                "description": (
                    "Coordinate clean -> compact -> analyze transcript processing."
                ),
            }
        ]
    }
    assert task_service.run_task("transcription_pipeline", input_text="sample") == {
        "ok": True,
        "task": "transcription_pipeline",
        "result": "analyzed: sample",
    }
    with pytest.raises(LookupError, match="Unknown task: missing"):
        task_service.run_task("missing")
