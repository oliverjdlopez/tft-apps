"""Offline contract tests for the development database benchmark runner."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from scripts.benchmarks import main as benchmark_main
from scripts.benchmarks import utils as benchmark_utils
from scripts.benchmarks.models import BenchmarkCase, InvocationRecord
from domain.tools.db_tools import utils as db_tool_utils


def _case(
    *,
    expected_kind: str = "table",
    group_by: tuple[str, ...] = ("unit_name",),
) -> BenchmarkCase:
    """Build a small representative benchmark case for result validation."""
    return BenchmarkCase(
        name="offline_case",
        tier="light",
        tool_name="rank_units",
        arguments={},
        description="Offline result validation case.",
        expected_kind=expected_kind,  # type: ignore[arg-type]
        group_by=group_by,
    )


def _table_result(
    *,
    group_by: list[str] | None = None,
    rows: list[dict[str, object]] | None = None,
    warnings: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    """Return one valid public table result with replaceable dimensions."""
    values = rows if rows is not None else [{"unit_name": "TFT17_Jinx"}]
    return {
        "kind": "table",
        "context": {
            "population": "synthetic test cohort",
            "population_boards": 64,
            "group_by": group_by if group_by is not None else ["unit_name"],
            "sort": [],
            "minimum_reportable_boards": 50,
        },
        "results": values,
        "page": {"offset": 0, "count": len(values), "has_more": False},
        "warnings": warnings or [],
    }


def _error_result(code: str) -> dict[str, object]:
    """Return one valid machine-readable database-tool error."""
    return {
        "kind": "error",
        "context": {},
        "error": {
            "code": code,
            "message": "bounded synthetic error",
            "retryable": False,
            "timeout_seconds": None,
        },
        "warnings": [],
    }


def test_cli_defaults_and_bounded_workloads() -> None:
    """Keep default execution sequential and expose only registered workloads."""
    args = benchmark_main.build_parser().parse_args([])

    assert args.suite == "all"
    assert args.light_runs == 3
    assert args.heavy_runs == 1
    assert args.concurrency == 1
    assert args.no_profile is False
    assert len(benchmark_main.WORKLOAD_DEFINITIONS) >= 7
    assert all(item.name and item.tool_name for item in benchmark_main.WORKLOAD_DEFINITIONS)


def test_cli_accepts_overrides_and_rejects_unknown_or_unsafe_values() -> None:
    """Parse supported runner overrides while rejecting unknown CLI options."""
    args = benchmark_main.build_parser().parse_args(
        ["--suite", "heavy", "--light-runs", "7", "--heavy-runs", "2", "--concurrency", "4", "--no-profile"]
    )

    assert (args.suite, args.light_runs, args.heavy_runs, args.concurrency) == (
        "heavy",
        7,
        2,
        4,
    )
    assert args.no_profile is True
    with pytest.raises(SystemExit):
        benchmark_main.build_parser().parse_args(["--unknown-option"])
    with pytest.raises(SystemExit):
        benchmark_main.build_parser().parse_args(["--concurrency", "5"])


def test_result_validation_rejects_wrong_family_and_grouping() -> None:
    """Require each case to receive its declared result family and table grain."""
    wrong_family = _error_result("database_error")
    normalized, status, _ = benchmark_utils.validate_tool_result(
        _case(), {"kind": "resolution", "context": {"minimum_reportable_boards": 50}, "results": [], "warnings": []}
    )
    assert normalized["kind"] == "resolution"
    assert status == "invalid_result"

    _, grouping_status, _ = benchmark_utils.validate_tool_result(
        _case(group_by=("unit_name", "item_name")), _table_result()
    )
    assert grouping_status == "invalid_result"
    _, missing_row_group_status, _ = benchmark_utils.validate_tool_result(
        _case(), _table_result(rows=[{"unrelated": "value"}])
    )
    assert missing_row_group_status == "invalid_result"
    _, error_status, _ = benchmark_utils.validate_tool_result(_case(), wrong_family)
    assert error_status == "tool_error"


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [("invalid_input", "invalid_input"), ("validation_error", "invalid_input"), ("database_error", "tool_error")],
)
def test_sdk_error_families_remain_distinct(code: str, expected_status: str) -> None:
    """Classify structured SDK tool errors without treating them as valid data."""
    _, status, _ = benchmark_utils.validate_tool_result(_case(), _error_result(code))
    assert status == expected_status


def test_tool_argument_validation_rejects_unknown_fields_before_callback(monkeypatch) -> None:
    """Reject unrecognized tool arguments before any SDK callback can run."""
    called = False

    async def callback(_context, _payload):
        nonlocal called
        called = True
        return _table_result()

    tool = SimpleNamespace(
        name="rank_units",
        params_json_schema={
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "additionalProperties": False,
        },
        on_invoke_tool=callback,
        timeout_seconds=1,
    )
    monkeypatch.setattr(benchmark_utils, "get_tool", lambda _name: tool)
    case = replace(_case(), arguments={"unexpected": True})

    record = asyncio.run(
        benchmark_utils.invoke_tool(case, "timed", 0, "run", [])
    )

    assert record.status == "invalid_input"
    assert record.error_type == "ValidationError"
    assert called is False


def test_result_validation_marks_empty_and_suppressed_data_insufficient() -> None:
    """Do not count empty or privacy-suppressed outputs as benchmark success."""
    _, empty_status, _ = benchmark_utils.validate_tool_result(
        _case(), _table_result(rows=[])
    )
    _, suppressed_status, _ = benchmark_utils.validate_tool_result(
        _case(),
        _table_result(warnings=[{"code": "sample_suppressed", "message": "small group"}]),
    )

    assert empty_status == "insufficient_data"
    assert suppressed_status == "insufficient_data"


def test_timing_statistics_include_successful_timed_samples_only() -> None:
    """Keep failures and warmups out of timing counts and p95 percentiles."""
    records = [
        InvocationRecord("case", "timed", index, str(index), float(index), status)
        for index, status in enumerate(["success"] * 19 + ["timeout"])
    ]
    records.append(InvocationRecord("case", "warmup", 0, "warmup", 999.0, "success"))

    values = benchmark_utils.numeric_values(records, "elapsed_ms")
    summary = benchmark_utils.timing_summary(values)
    assert len(values) == 19
    assert summary == {"count": 19, "p50_ms": 9.0}

    records.append(InvocationRecord("case", "timed", 20, "20", 20.0, "success"))
    summary_20 = benchmark_utils.timing_summary(
        benchmark_utils.numeric_values(records, "elapsed_ms")
    )
    assert summary_20["count"] == 20
    assert summary_20["p50_ms"] == 9.5
    assert summary_20["p95_ms"] == 18.1


def test_timeout_cancels_callback_and_respects_tool_timeout_override(monkeypatch) -> None:
    """Cancel a stalled tool callback and honor its registered timeout override."""
    cleaned = asyncio.Event()

    async def slow_callback(_context, _payload):
        try:
            await asyncio.sleep(1)
        finally:
            cleaned.set()

    tool = SimpleNamespace(
        name="rank_units",
        params_json_schema={"type": "object", "properties": {}, "additionalProperties": False},
        on_invoke_tool=slow_callback,
        timeout_seconds=0.001,
    )
    monkeypatch.setattr(benchmark_utils, "get_tool", lambda _name: tool)
    record = asyncio.run(
        benchmark_utils.invoke_tool(_case(), "timed", 0, "run", [])
    )

    assert record.status == "timeout"
    assert cleaned.is_set()


def test_session_scope_restores_opener_and_disables_schema_creation(monkeypatch) -> None:
    """Restore the production DB opener after the benchmark-only scope exits."""
    original = db_tool_utils.open_db
    calls: list[dict[str, object]] = []

    def fake_open_db(*args, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(benchmark_utils, "_real_open_db", fake_open_db)
    with pytest.raises(RuntimeError):
        with benchmark_utils.benchmark_session_scope():
            assert db_tool_utils.open_db() is not None
            raise RuntimeError("exercise cleanup")

    assert calls == [{"ensure_schema": False}]
    assert db_tool_utils.open_db is original


def test_list_workloads_does_not_resolve_or_connect_to_database(monkeypatch, capsys) -> None:
    """List benchmark definitions without starting orchestration or DB cleanup."""
    def unexpected(*_args, **_kwargs):
        raise AssertionError("--list must not enter database orchestration")

    monkeypatch.setattr(benchmark_main, "run_benchmark", unexpected)
    monkeypatch.setattr(benchmark_main, "shutdown_database_worker", unexpected)

    assert benchmark_main.main(["--list"]) == 0
    output = capsys.readouterr().out
    assert "resolve_names" in output
    assert "cohort_item_deltas" in output


def test_discovery_ignores_rows_from_failed_results_and_stops_after_timeout(monkeypatch) -> None:
    """Never bind an anchor from a failed result or schedule another discovery call."""
    failed = InvocationRecord("failed", "discovery", 0, "failed", 1.0, "invalid_result")
    failed.result = _table_result()
    assert benchmark_main.rows_from(failed) == []

    calls = []

    async def timed_out(case, *_args, **_kwargs):
        calls.append(case.name)
        return InvocationRecord(case.name, "discovery", 0, "timeout", 1.0, "timeout")

    monkeypatch.setattr(benchmark_main, "invoke_tool", timed_out)
    anchors, errors, _, timeout_case = asyncio.run(
        benchmark_main.discover_anchors(
            list(benchmark_main.WORKLOAD_DEFINITIONS), "run", []
        )
    )
    assert calls == ["discovery_traits"]
    assert anchors == {}
    assert errors["discovery"] == "Trait discovery timed out."
    assert timeout_case == "discovery_traits"


def test_discovery_timeout_marks_every_selected_case_not_run(monkeypatch, tmp_path) -> None:
    """Report each workload and avoid all timed calls after discovery times out."""
    async def timed_out_discovery(*_args, **_kwargs):
        return {}, {"discovery": "timed out"}, {}, "discovery_traits"

    async def unexpected_case(*_args, **_kwargs):
        raise AssertionError("timed workload must not run")

    monkeypatch.setattr(benchmark_main, "discover_anchors", timed_out_discovery)
    monkeypatch.setattr(benchmark_main, "run_case", unexpected_case)
    monkeypatch.setattr(benchmark_main, "safe_database_metadata", lambda: {})
    monkeypatch.setattr(benchmark_main, "benchmark_session_scope", nullcontext)
    monkeypatch.setattr("db.session.database_label", lambda: "synthetic-test-target")
    args = benchmark_main.build_parser().parse_args(
        ["--output-root", str(tmp_path), "--no-profile"]
    )

    assert asyncio.run(benchmark_main.run_benchmark(args)) == 1
    summaries = list(tmp_path.glob("*/summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert len(summary["cases"]) == len(benchmark_main.WORKLOAD_DEFINITIONS)
    assert {case["status"] for case in summary["cases"]} == {"not_run_timeout"}

