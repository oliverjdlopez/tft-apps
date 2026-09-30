"""Structured, correlated performance tracing for video analysis jobs."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import resource
import sys
import threading
import time
from typing import Any, Callable, Iterator


LOGGER = logging.getLogger("vod.performance")
_TRACE_FIELDS: ContextVar[dict[str, Any]] = ContextVar("vod_trace_fields", default={})
_TRACE_LISTENERS: ContextVar[tuple[Callable[[dict[str, Any]], None], ...]] = ContextVar(
    "vod_trace_listeners", default=()
)
_RESOURCE_BASELINE: ContextVar[tuple[float, float] | None] = ContextVar(
    "vod_resource_baseline", default=None
)
_JSONL_PATH: Path | None = None
_JSONL_LOCK = threading.Lock()


def configure_performance_logging(jsonl_path: Path | str | None = None) -> None:
    """Emit VOD traces to stdout and optionally persist structured JSONL."""
    global _JSONL_PATH
    if not LOGGER.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s VOD_TRACE %(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    configured_path = jsonl_path or os.environ.get("VOD_TRACE_JSONL")
    if configured_path:
        _JSONL_PATH = Path(configured_path).resolve()
        _JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    else:
        _JSONL_PATH = None


@contextmanager
def trace_context(**fields: Any) -> Iterator[None]:
    """Attach correlation fields to all trace events in this execution context."""
    token = _TRACE_FIELDS.set({**_TRACE_FIELDS.get(), **fields})
    try:
        yield
    finally:
        _TRACE_FIELDS.reset(token)


def set_trace_context(**fields: Any) -> None:
    """Replace long-lived correlation fields for the current worker context."""
    _TRACE_FIELDS.set(dict(fields))


@contextmanager
def capture_trace_events() -> Iterator[list[dict[str, Any]]]:
    """Capture structured events while continuing to emit configured logs."""
    events: list[dict[str, Any]] = []
    listeners = _TRACE_LISTENERS.get()
    token = _TRACE_LISTENERS.set((*listeners, events.append))
    try:
        yield events
    finally:
        _TRACE_LISTENERS.reset(token)


def detailed_profiling_enabled() -> bool:
    return os.environ.get("VOD_DETAILED_PROFILING", "").lower() in {"1", "true", "yes", "on"}


def trace_event(event: str, **fields: Any) -> None:
    """Log one machine-searchable event and send its structured form to sinks."""
    merged = {**_TRACE_FIELDS.get(), **fields}
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "monotonic_seconds": time.perf_counter(),
        "event": event,
        **merged,
    }
    if LOGGER.isEnabledFor(logging.INFO):
        rendered = " ".join(f"{key}={value}" for key, value in merged.items())
        LOGGER.info("event=%s %s", event, rendered)
    for listener in _TRACE_LISTENERS.get():
        listener(payload)
    if _JSONL_PATH is not None:
        with _JSONL_LOCK:
            with _JSONL_PATH.open("a", encoding="utf-8") as destination:
                destination.write(json.dumps(payload, sort_keys=True, default=str) + "\n")


def _current_rss_bytes() -> int | None:
    try:
        resident_pages = int(Path("/proc/self/statm").read_text().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):
        return None


def trace_resources(phase: str, *, include_cuda: bool = True, **extra_fields: Any) -> None:
    """Record process CPU/RSS and, when available, CUDA utilization and memory."""
    now = time.perf_counter()
    process_now = time.process_time()
    baseline = _RESOURCE_BASELINE.get()
    cpu_percent = None
    if baseline is not None and now > baseline[0]:
        cpu_percent = (process_now - baseline[1]) / (now - baseline[0]) * 100
    _RESOURCE_BASELINE.set((now, process_now))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    fields: dict[str, Any] = {
        "phase": phase,
        "process_cpu_percent": round(cpu_percent, 2) if cpu_percent is not None else None,
        "process_cpu_seconds": round(process_now, 6),
        "rss_bytes": _current_rss_bytes(),
        "max_rss_bytes": int(usage.ru_maxrss * (1024 if sys.platform != "darwin" else 1)),
        **extra_fields,
    }
    if include_cuda:
        try:
            import torch

            if torch.cuda.is_available():
                device = torch.cuda.current_device()
                free_bytes, total_bytes = torch.cuda.mem_get_info(device)
                fields.update(
                    cuda_device=device,
                    cuda_memory_free_bytes=free_bytes,
                    cuda_memory_total_bytes=total_bytes,
                    torch_memory_allocated_bytes=torch.cuda.memory_allocated(device),
                    torch_memory_reserved_bytes=torch.cuda.memory_reserved(device),
                    torch_peak_memory_allocated_bytes=torch.cuda.max_memory_allocated(device),
                )
                try:
                    fields["cuda_utilization_percent"] = torch.cuda.utilization(device)
                except Exception as exc:  # noqa: BLE001 - utilization may require pynvml
                    fields["cuda_utilization_error"] = type(exc).__name__
        except Exception as exc:  # noqa: BLE001 - resource telemetry must not fail a job
            fields["cuda_metrics_error"] = type(exc).__name__
    trace_event("resource_snapshot", **fields)
