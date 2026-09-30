"""Transcript task orchestration."""

from __future__ import annotations

import json
from typing import Any

from agents import Runner

from domain.assistants import (
    build_assistant_instructions,
    create_assistant,
    render_assistant_input,
)
from domain.assistants.constants import AssistantName
from domain.assistants.models import (
    CleanTranscriptOutput,
    CompactTranscriptOutput,
)


TRANSCRIPTION_TASK_NAME = "transcription_pipeline"
TRANSCRIPTION_TASK_DESCRIPTION = (
    "Coordinate clean -> compact -> analyze transcript processing."
)


def run_transcription_pipeline(input_text: str = "") -> str:
    """Clean, compact, and analyze one transcript."""
    edits = _run_agent_sync(
        AssistantName.CLEAN_TRANSCRIPT,
        input_text,
        output_type=CleanTranscriptOutput,
    )
    cleaned = apply_clean_transcript_edits(input_text, edits)
    compacted_output = _run_agent_sync(
        AssistantName.COMPACT_TRANSCRIPT,
        cleaned,
        output_type=CompactTranscriptOutput,
    )
    compacted = (
        compacted_output.root
        if isinstance(compacted_output, CompactTranscriptOutput)
        else compacted_output
    )
    return str(_run_agent_sync(AssistantName.ANALYZE_TRANSCRIPT, compacted))


def _run_agent_sync(
    name: str,
    input_text: str,
    *,
    output_type: type[Any] | None = None,
) -> Any:
    agent = create_assistant(
        name,
        instructions=build_assistant_instructions(name, input_text),
        output_type=output_type,
    )
    return Runner.run_sync(
        agent,
        input=render_assistant_input(name, input_text),
    ).final_output


def apply_clean_transcript_edits(
    original_text: str, edits_response: str | CleanTranscriptOutput
) -> str:
    """Apply the clean_transcript assistant's edit list onto the original JSONL.

    ``clean_transcript`` no longer re-emits the full transcript; it returns a
    JSON object of the form ``{"edits": [...]}`` referencing lines by ``id``.
    This rebuilds the cleaned transcript by applying those edits over the
    original segments, leaving every unmentioned line verbatim. If the input is
    not JSONL or the response can't be parsed, the original text is returned
    unchanged so the pipeline degrades gracefully.
    """
    records, has_records = _parse_transcript(original_text)
    edits = _parse_edits(edits_response)
    if not has_records or edits is None:
        return original_text

    by_id: dict[Any, dict[str, Any]] = {
        record["id"]: record
        for record in records
        if isinstance(record, dict) and "id" in record
    }
    dropped: set[Any] = set()

    for edit in edits:
        if not isinstance(edit, dict):
            continue
        if "delete" in edit:
            dropped.update(_as_id_list(edit["delete"]))
            continue
        if "merge" in edit:
            ids = _as_id_list(edit["merge"])
            if not ids:
                continue
            head = by_id.get(ids[0])
            if head is None:
                continue
            if "text" in edit:
                head["text"] = edit["text"]
            tail = by_id.get(ids[-1])
            if tail is not None and "end" in tail:
                head["end"] = tail["end"]
            dropped.update(ids[1:])
            continue
        if "id" in edit and "text" in edit:
            record = by_id.get(edit["id"])
            if record is not None:
                record["text"] = edit["text"]

    out_lines: list[str] = []
    for record in records:
        if isinstance(record, dict):
            if record.get("id") in dropped:
                continue
            out_lines.append(json.dumps(record, ensure_ascii=False))
        else:
            out_lines.append(record)
    return "\n".join(out_lines)


def _parse_transcript(text: str) -> tuple[list[Any], bool]:
    """Parse JSONL into a list of dict records, keeping raw lines as fallback."""
    records: list[Any] = []
    has_records = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            records.append(line)
            continue
        if isinstance(obj, dict):
            records.append(obj)
            has_records = True
        else:
            records.append(line)
    return records, has_records


def _parse_edits(response: str | CleanTranscriptOutput) -> list[Any] | None:
    """Extract the ``edits`` list from the assistant response, if present."""
    if isinstance(response, CleanTranscriptOutput):
        return [edit.model_dump(mode="json") for edit in response.edits]

    start = response.find("{")
    end = response.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        payload = json.loads(response[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    edits = payload.get("edits")
    return edits if isinstance(edits, list) else None


def _as_id_list(value: Any) -> list[Any]:
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, int)]
    return []


__all__ = [
    "TRANSCRIPTION_TASK_DESCRIPTION",
    "TRANSCRIPTION_TASK_NAME",
    "apply_clean_transcript_edits",
    "run_transcription_pipeline",
]
