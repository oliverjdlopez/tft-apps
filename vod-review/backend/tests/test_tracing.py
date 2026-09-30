import json

from backend import tracing


def test_trace_context_correlates_events_and_writes_jsonl(tmp_path, monkeypatch):
    output = tmp_path / "trace.jsonl"
    monkeypatch.setattr(tracing, "_JSONL_PATH", None)
    tracing.configure_performance_logging(output)

    with tracing.trace_context(job_id="job-1", video_id="video-1"), tracing.trace_context(
        batch_index=2, batch_capacity=64, actual_batch_size=17
    ), tracing.capture_trace_events() as events:
        tracing.trace_event("stage", elapsed_ms=1.25)

    assert events[0]["event"] == "stage"
    assert events[0]["job_id"] == "job-1"
    assert events[0]["video_id"] == "video-1"
    assert events[0]["batch_index"] == 2
    assert events[0]["batch_capacity"] == 64
    assert events[0]["actual_batch_size"] == 17
    assert json.loads(output.read_text())["elapsed_ms"] == 1.25


def test_resource_snapshot_is_captured_without_optional_cuda_metrics(monkeypatch):
    monkeypatch.setattr(tracing, "_JSONL_PATH", None)
    with tracing.capture_trace_events() as events:
        tracing.trace_resources("test", batch_index=3)

    snapshot = events[0]
    assert snapshot["event"] == "resource_snapshot"
    assert snapshot["phase"] == "test"
    assert snapshot["batch_index"] == 3
    assert snapshot["process_cpu_seconds"] >= 0
    assert snapshot["max_rss_bytes"] > 0
