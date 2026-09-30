"""Execution, logging, timing, and profiling mechanics for DB benchmarks."""

from __future__ import annotations

import asyncio
import cProfile
from contextlib import contextmanager
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
import logging
from pathlib import Path
import pstats
import statistics
import time
from typing import Any, Iterator, Mapping

from agents.tool_context import ToolContext

from common.serialization import to_jsonable
from domain.tools import get_tool
from domain.tools.db_tools import utils as db_tool_utils

from .models import (
    BenchmarkCase,
    BenchmarkPhase,
    CaseReport,
    InvocationRecord,
    ProfileArtifact,
)


BENCHMARK_LOGGER_NAME = "tft.benchmarks"
_LOGGER_NAMES = (
    BENCHMARK_LOGGER_NAME,
    "tft.analysis.db",
    "tft.analysis.ranking_tools",
)


class JsonlEventHandler(logging.Handler):
    """Write bounded logging records to a JSON-lines benchmark artifact."""

    def __init__(self, path: Path) -> None:
        """Open the run-specific event file.

        Args:
            path: JSON-lines output path for benchmark and DB diagnostics.
        """
        super().__init__(level=logging.DEBUG)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.records: list[dict[str, Any]] = []
        self._stream = path.open("a", encoding="utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        """Serialize one logging record without exposing logger arguments.

        Args:
            record: Logging record emitted by the benchmark or DB tools.
        """
        try:
            payload = {
                "timestamp": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            self.records.append(payload)
            self._stream.write(json.dumps(payload, default=str, sort_keys=True) + "\n")
            self._stream.flush()
        except Exception:
            self.handleError(record)

    def close(self) -> None:
        """Flush and close the run-specific event file."""
        try:
            self._stream.close()
        finally:
            super().close()


@contextmanager
def event_logging(path: Path) -> Iterator[JsonlEventHandler]:
    """Capture benchmark and existing DB diagnostics in one JSONL file.

    Args:
        path: Run-specific output path.

    Yields:
        The handler, including in-memory records used to correlate DB timings.
    """
    handler = JsonlEventHandler(path)
    logger_state: dict[str, tuple[int, bool]] = {}
    loggers = [logging.getLogger(name) for name in _LOGGER_NAMES]
    for logger in loggers:
        logger_state[logger.name] = (logger.level, logger.propagate)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.addHandler(handler)
    try:
        yield handler
    finally:
        for logger in loggers:
            logger.removeHandler(handler)
            level, propagate = logger_state[logger.name]
            logger.setLevel(level)
            logger.propagate = propagate
        handler.close()


def log_event(event: str, **details: Any) -> None:
    """Write one structured benchmark lifecycle event.

    Args:
        event: Stable event name.
        **details: Bounded JSON-compatible event details.
    """
    payload = {"event": event, **details}
    logging.getLogger(BENCHMARK_LOGGER_NAME).info(
        "benchmark_event %s", json.dumps(payload, default=str, sort_keys=True)
    )


def bounded_text(value: Any, limit: int = 400) -> str:
    """Convert diagnostic text to a bounded single-line string.

    Args:
        value: Value to render.
        limit: Maximum number of characters to retain.

    Returns:
        A compact diagnostic string.
    """
    text = str(value).replace("\n", " ").replace("\r", " ").strip()
    return text if len(text) <= limit else f"{text[:limit]}..."


def normalize_tool_result(value: Any) -> Any:
    """Normalize an SDK callback result to JSON-compatible Python data.

    Args:
        value: Raw result returned by a registered SDK tool callback.

    Returns:
        A JSON-compatible result, decoding a JSON string when possible.
    """
    result = to_jsonable(value)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return result
    return result


def result_metadata(result: Any) -> dict[str, Any]:
    """Summarize a tool result without retaining its rows or full payload.

    Args:
        result: Normalized tool result.

    Returns:
        Bounded keys, count fields, and error presence metadata.
    """
    if not isinstance(result, Mapping):
        return {"result_type": type(result).__name__}
    metadata: dict[str, Any] = {
        "result_type": "object",
        "keys": sorted(str(key) for key in result),
    }
    metadata["kind"] = result.get("kind")
    page = result.get("page")
    if isinstance(page, Mapping):
        metadata["page_count"] = page.get("count")
        metadata["has_more"] = page.get("has_more")
    results = result.get("results")
    if isinstance(results, list):
        metadata["results_length"] = len(results)
    if result.get("kind") == "error":
        metadata["has_error"] = True
        error = result.get("error")
        if isinstance(error, Mapping):
            metadata["error_code"] = error.get("code")
    return metadata


def parse_log_payload(message: str, prefix: str) -> dict[str, Any] | None:
    """Parse a JSON payload appended to a structured logger message.

    Args:
        message: Complete logger message.
        prefix: Exact text before the JSON payload.

    Returns:
        Parsed object, or ``None`` when the message is not a matching payload.
    """
    if not message.startswith(prefix):
        return None
    try:
        payload = json.loads(message[len(prefix) :])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def database_timing_for_call(
    records: list[dict[str, Any]], call_id: str
) -> dict[str, Any]:
    """Extract the existing DB-boundary timing event for one call.

    Args:
        records: In-memory records collected by ``JsonlEventHandler``.
        call_id: Unique DB-tool call identifier.

    Returns:
        Acquisition, execution, total, and pool fields when available.
    """
    for record in reversed(records):
        payload = parse_log_payload(
            str(record.get("message", "")), "analysis_db_call "
        )
        if payload is not None and payload.get("call_id") == call_id:
            return {
                key: payload.get(key)
                for key in (
                    "acquisition_ms",
                    "execution_ms",
                    "total_ms",
                    "outcome",
                    "checkouts",
                    "checkins",
                    "size",
                    "checked_out",
                    "overflow",
                    "available",
                )
                if key in payload
            }
    return {}


def call_id_for(
    run_id: str, case_name: str, phase: BenchmarkPhase, iteration: int
) -> str:
    """Build a stable, diagnostic-safe call ID for one benchmark invocation.

    Args:
        run_id: Unique benchmark run identifier.
        case_name: Workload identifier.
        phase: Invocation phase.
        iteration: Zero-based phase iteration.

    Returns:
        A bounded call ID suitable for existing DB diagnostics.
    """
    return f"benchmark-{run_id}-{case_name}-{phase}-{iteration}"


def registered_tool_callback(tool: Any) -> Any:
    """Return the registered tool callback without runner error decoration.

    The Agents SDK stores schema parsing and the actual function invocation in
    ``_invoke_tool_impl`` behind its runner-oriented failure handler. The
    benchmark has its own bounded failure recording, so it uses that validated
    implementation when available and falls back to the public callback for
    other SDK tool implementations.

    Args:
        tool: Registered SDK tool returned by the native tool registry.

    Returns:
        Async callback that validates arguments and invokes the registered tool.
    """
    callback = getattr(tool, "on_invoke_tool")
    return getattr(callback, "_invoke_tool_impl", callback)


async def invoke_tool(
    case: BenchmarkCase,
    phase: BenchmarkPhase,
    iteration: int,
    run_id: str,
    event_records: list[dict[str, Any]],
    *,
    keep_result: bool = False,
) -> InvocationRecord:
    """Invoke one registered database tool and record bounded diagnostics.

    Args:
        case: Fully bound workload case.
        phase: Discovery, warmup, timed, or profile phase.
        iteration: Zero-based phase iteration.
        run_id: Unique benchmark run identifier.
        event_records: In-memory logger records for DB timing correlation.
        keep_result: Retain the normalized result for representative-name discovery.

    Returns:
        One invocation record; failures are represented instead of raised.
    """
    call_id = call_id_for(run_id, case.name, phase, iteration)
    log_event(
        "invocation_start",
        case=case.name,
        phase=phase,
        iteration=iteration,
        tool=case.tool_name,
        call_id=call_id,
    )
    started_at = time.perf_counter_ns()
    result: Any = None
    status = "success"
    error_type: str | None = None
    error: str | None = None
    try:
        tool = get_tool(case.tool_name)
        payload = json.dumps(case.arguments, default=str, sort_keys=True)
        context = ToolContext(
            None,
            tool_name=case.tool_name,
            tool_call_id=call_id,
            tool_arguments=payload,
        )
        tool_timeout = float(getattr(tool, "timeout_seconds", 60.0) or 60.0)
        result = normalize_tool_result(
            await asyncio.wait_for(
                registered_tool_callback(tool)(context, payload),
                timeout=tool_timeout,
            )
        )
        if isinstance(result, Mapping) and "error" in result:
            status = "tool_error"
            error_type = "ToolResultError"
            error = bounded_text(result.get("error"))
    except Exception as exc:  # Benchmark runs should continue to later cases.
        status = "exception"
        error_type = type(exc).__name__
        error = bounded_text(exc)
    elapsed_ms = (time.perf_counter_ns() - started_at) / 1_000_000
    metadata = result_metadata(result)
    timing = database_timing_for_call(event_records, call_id)
    record = InvocationRecord(
        case_name=case.name,
        phase=phase,
        iteration=iteration,
        call_id=call_id,
        elapsed_ms=round(elapsed_ms, 3),
        status=status,
        result_metadata=metadata,
        database_timing=timing,
        error_type=error_type,
        error=error,
        result=result if keep_result else None,
    )
    log_event(
        "invocation_complete",
        case=case.name,
        phase=phase,
        iteration=iteration,
        tool=case.tool_name,
        call_id=call_id,
        elapsed_ms=record.elapsed_ms,
        status=status,
        result_metadata=metadata,
        database_timing=timing,
        error_type=error_type,
    )
    return record


class WorkerProfilingExecutor(ThreadPoolExecutor):
    """Profile one ``run_db_tool`` worker submission with ``cProfile``."""

    def __init__(self, stats_path: Path) -> None:
        """Create a single-worker executor writing to one profile artifact.

        Args:
            stats_path: Destination for binary ``pstats`` data.
        """
        super().__init__(max_workers=1, thread_name_prefix="tft-db-profile")
        self.stats_path = stats_path

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        """Profile the submitted worker function before returning its future.

        Args:
            fn: Worker function submitted by ``run_db_tool``.
            *args: Positional worker arguments.
            **kwargs: Keyword worker arguments.

        Returns:
            Future for the profiled worker call.
        """

        def profiled_call() -> Any:
            """Run the worker while collecting cumulative function timings."""
            profiler = cProfile.Profile()
            try:
                return profiler.runcall(fn, *args, **kwargs)
            finally:
                self.stats_path.parent.mkdir(parents=True, exist_ok=True)
                profiler.dump_stats(str(self.stats_path))

        return super().submit(profiled_call)


def write_profile_text(stats_path: Path, text_path: Path) -> None:
    """Render the top cumulative-time profile entries to text.

    Args:
        stats_path: Binary profile created by ``cProfile``.
        text_path: Human-readable output path.
    """
    output = io.StringIO()
    pstats.Stats(str(stats_path), stream=output).strip_dirs().sort_stats(
        "cumulative"
    ).print_stats(50)
    text_path.write_text(output.getvalue(), encoding="utf-8")


async def profile_case(
    case: BenchmarkCase,
    run_id: str,
    profile_dir: Path,
    event_records: list[dict[str, Any]],
) -> tuple[InvocationRecord, ProfileArtifact]:
    """Profile one case inside the existing database worker thread.

    Args:
        case: Fully bound workload case.
        run_id: Unique benchmark run identifier.
        profile_dir: Run-specific profile output directory.
        event_records: In-memory logger records for DB timing correlation.

    Returns:
        The profile invocation record and generated artifact metadata.
    """
    stats_path = profile_dir / f"{case.name}.prof"
    text_path = profile_dir / f"{case.name}.txt"
    profile_dir.mkdir(parents=True, exist_ok=True)
    executor = WorkerProfilingExecutor(stats_path)
    original_executor = db_tool_utils._DB_TOOL_EXECUTOR
    db_tool_utils._DB_TOOL_EXECUTOR = executor
    try:
        record = await invoke_tool(
            case,
            "profile",
            0,
            run_id,
            event_records,
        )
    finally:
        db_tool_utils._DB_TOOL_EXECUTOR = original_executor
        executor.shutdown(wait=True)
    try:
        write_profile_text(stats_path, text_path)
        artifact = ProfileArtifact(
            stats_path=str(stats_path),
            text_path=str(text_path),
            status=record.status,
            error=record.error,
        )
    except Exception as exc:
        artifact = ProfileArtifact(
            stats_path=str(stats_path),
            text_path=str(text_path),
            status="profile_error",
            error=bounded_text(exc),
        )
    return record, artifact


async def run_case(
    case: BenchmarkCase,
    run_id: str,
    iterations: int,
    profile_enabled: bool,
    profile_dir: Path,
    event_records: list[dict[str, Any]],
) -> CaseReport:
    """Run warmup, timed, and optional profile phases for one case.

    Args:
        case: Fully bound workload case.
        run_id: Unique benchmark run identifier.
        iterations: Number of timed invocations.
        profile_enabled: Whether to run the separate worker profile pass.
        profile_dir: Run-specific profile output directory.
        event_records: In-memory logger records for DB timing correlation.

    Returns:
        Case report containing all invocation metadata and status.
    """
    report = CaseReport(case=case)
    warmup = await invoke_tool(case, "warmup", 0, run_id, event_records)
    report.records.append(warmup)
    for iteration in range(iterations):
        report.records.append(
            await invoke_tool(case, "timed", iteration, run_id, event_records)
        )
    if profile_enabled:
        profile_record, artifact = await profile_case(
            case, run_id, profile_dir, event_records
        )
        report.records.append(profile_record)
        report.profile = artifact
    failures = [record for record in report.records if record.status != "success"]
    if failures:
        report.status = "failed"
        report.error = failures[0].error or failures[0].error_type
    return report


def numeric_values(records: list[InvocationRecord], field: str) -> list[float]:
    """Extract numeric timing values from timed invocation records.

    Args:
        records: Invocation records for one case.
        field: ``elapsed_ms`` or a DB timing field.

    Returns:
        Numeric values from successful or failed timed records.
    """
    values: list[float] = []
    for record in records:
        if record.phase != "timed":
            continue
        value = record.elapsed_ms if field == "elapsed_ms" else record.database_timing.get(field)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def timing_summary(values: list[float]) -> dict[str, Any]:
    """Summarize timing samples without implying statistical rigor.

    Args:
        values: Timing values in milliseconds.

    Returns:
        Count and basic min/median/mean/max values.
    """
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min_ms": round(min(values), 3),
        "median_ms": round(statistics.median(values), 3),
        "mean_ms": round(statistics.fmean(values), 3),
        "max_ms": round(max(values), 3),
    }


def invocation_dict(record: InvocationRecord) -> dict[str, Any]:
    """Serialize an invocation while omitting any retained discovery result.

    Args:
        record: Invocation record to serialize.

    Returns:
        JSON-compatible bounded invocation metadata.
    """
    return {
        "case": record.case_name,
        "phase": record.phase,
        "iteration": record.iteration,
        "call_id": record.call_id,
        "elapsed_ms": record.elapsed_ms,
        "status": record.status,
        "result_metadata": record.result_metadata,
        "database_timing": record.database_timing,
        "error_type": record.error_type,
        "error": record.error,
    }


def case_report_dict(report: CaseReport) -> dict[str, Any]:
    """Serialize one case report with aggregate and individual timings.

    Args:
        report: Completed case report.

    Returns:
        JSON-compatible case summary.
    """
    return {
        "name": report.case.name,
        "tier": report.case.tier,
        "tool": report.case.tool_name,
        "description": report.case.description,
        "status": report.status,
        "error": report.error,
        "timing_ms": {
            "end_to_end": timing_summary(numeric_values(report.records, "elapsed_ms")),
            "database_acquisition": timing_summary(
                numeric_values(report.records, "acquisition_ms")
            ),
            "database_execution": timing_summary(
                numeric_values(report.records, "execution_ms")
            ),
            "database_total": timing_summary(
                numeric_values(report.records, "total_ms")
            ),
        },
        "samples": [invocation_dict(record) for record in report.records],
        "profile": (
            {
                "stats_path": report.profile.stats_path,
                "text_path": report.profile.text_path,
                "status": report.profile.status,
                "error": report.profile.error,
            }
            if report.profile is not None
            else None
        ),
    }


def write_json(path: Path, payload: Any) -> None:
    """Write an indented, deterministic JSON artifact.

    Args:
        path: Destination path.
        payload: JSON-compatible value to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, default=str, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def shutdown_database_worker() -> None:
    """Stop the shared DB-tool worker pool before the CLI process exits.

    The application keeps this executor for its process lifetime. The
    short-lived development benchmark must shut it down explicitly so failed
    connection attempts still produce artifacts and a prompt exit status.
    """
    executor = db_tool_utils._DB_TOOL_EXECUTOR
    executor.shutdown(wait=True, cancel_futures=True)
