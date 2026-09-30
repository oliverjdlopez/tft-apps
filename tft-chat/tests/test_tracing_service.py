from __future__ import annotations

import json
from pathlib import Path

from services.tracing_service import LocalTraceRecorder


class FakeTrace:
    trace_id = "trace_test"
    group_id = "group_test"
    metadata = {"run_id": "run_test"}

    def export(self) -> dict[str, object]:
        return {
            "object": "trace",
            "id": self.trace_id,
            "workflow_name": "test",
            "group_id": self.group_id,
            "metadata": self.metadata,
        }


class FakeSpan:
    trace_id = "trace_test"
    span_id = "span_test"
    parent_id = None

    def export(self) -> dict[str, object]:
        return {
            "object": "trace.span",
            "id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "started_at": "2026-07-06T00:00:00+00:00",
            "ended_at": "2026-07-06T00:00:01+00:00",
            "span_data": {"type": "function", "name": "example"},
            "error": None,
        }


def test_local_trace_recorder_writes_trace_and_span_events(tmp_path: Path) -> None:
    recorder = LocalTraceRecorder(tmp_path)
    trace = FakeTrace()
    span = FakeSpan()

    recorder.on_trace_start(trace)
    recorder.on_span_start(span)
    recorder.on_span_end(span)
    recorder.on_trace_end(trace)

    path = tmp_path / "trace_test.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]

    assert [event["event"] for event in events] == [
        "trace_start",
        "span_start",
        "span_end",
        "trace_end",
    ]
    assert events[1]["span"]["span_data"]["name"] == "example"
