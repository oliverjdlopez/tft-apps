from __future__ import annotations

from types import SimpleNamespace

import pytest

from domain.tasks import transcript
from domain.assistants import render_assistant_input
from domain.assistants import assistant_spec
from services import task_service


def test_transcription_pipeline_runs_the_three_assistants_in_order(monkeypatch) -> None:
    original = '{"id": 1, "text": "um hello"}\n{"id": 2, "text": "world"}'
    calls: list[tuple[str, str]] = []
    outputs = {
        "clean_transcript": '{"edits": [{"id": 1, "text": "hello"}]}',
        "compact_transcript": "compact transcript",
        "analyze_transcript": "analysis",
    }

    monkeypatch.setattr(
        transcript,
        "create_assistant",
        lambda name, **_kwargs: SimpleNamespace(name=name),
    )
    monkeypatch.setattr(
        transcript,
        "build_assistant_instructions",
        lambda name, _input: assistant_spec(name).system_prompt,
    )

    def fake_run_sync(agent, *, input):
        calls.append((agent.name, input))
        return SimpleNamespace(final_output=outputs[agent.name])

    monkeypatch.setattr(transcript.Runner, "run_sync", fake_run_sync)

    assert transcript.run_transcription_pipeline(original) == "analysis"
    assert calls == [
        ("clean_transcript", render_assistant_input("clean_transcript", original)),
        (
            "compact_transcript",
            render_assistant_input(
                "compact_transcript",
                '{"id": 1, "text": "hello"}\n{"id": 2, "text": "world"}',
            ),
        ),
        (
            "analyze_transcript",
            render_assistant_input("analyze_transcript", "compact transcript"),
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
