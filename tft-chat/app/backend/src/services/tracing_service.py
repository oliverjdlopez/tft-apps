"""Local OpenAI Agents SDK trace recording for development audits."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from common.paths import find_repo_root
from common.serialization import write_json_lines
from core.config import load_config

logger = logging.getLogger(__name__)

_PROCESSOR_REGISTERED = False
_PROCESSOR_LOCK = threading.Lock()


def local_tracing_enabled() -> bool:
    """Whether local trace JSONL recording should be installed."""
    return load_config().chat.local_tracing


def trace_dir() -> Path:
    configured = load_config().chat.trace_dir
    return configured if configured else find_repo_root() / "data" / "traces"


def trace_file_path(trace_id: str) -> Path:
    return trace_dir() / f"{trace_id}.jsonl"


class LocalTraceRecorder:
    """Tracing processor that mirrors SDK traces/spans into local JSONL files."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or trace_dir()
        self._lock = threading.Lock()

    def _path(self, trace_id: str) -> Path:
        return self.directory / f"{trace_id}.jsonl"

    def _record(self, trace_id: str, event: dict[str, Any]) -> None:
        try:
            with self._lock:
                write_json_lines(self._path(trace_id), [event], append=True)
        except Exception:  # noqa: BLE001 - tracing must never break agent execution.
            logger.exception("failed to write local trace event")

    def on_trace_start(self, trace: Any) -> None:
        self._record(
            trace.trace_id,
            {
                "event": "trace_start",
                "trace_id": trace.trace_id,
                "trace": trace.export(),
            },
        )

    def on_trace_end(self, trace: Any) -> None:
        self._record(
            trace.trace_id,
            {
                "event": "trace_end",
                "trace_id": trace.trace_id,
                "trace": trace.export(),
            },
        )

    def on_span_start(self, span: Any) -> None:
        exported = span.export()
        self._record(
            span.trace_id,
            {
                "event": "span_start",
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_id": span.parent_id,
                "span": exported,
            },
        )

    def on_span_end(self, span: Any) -> None:
        self._record(
            span.trace_id,
            {
                "event": "span_end",
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_id": span.parent_id,
                "span": span.export(),
            },
        )

    def shutdown(self) -> None:
        return None

    def force_flush(self) -> None:
        return None


def ensure_local_trace_processor() -> bool:
    """Register the local recorder once per process.

    Returns True when local recording is enabled, including when it had already
    been registered.
    """
    global _PROCESSOR_REGISTERED
    if not local_tracing_enabled():
        return False
    with _PROCESSOR_LOCK:
        if _PROCESSOR_REGISTERED:
            return True
        try:
            from agents.tracing import add_trace_processor

            add_trace_processor(LocalTraceRecorder())
            _PROCESSOR_REGISTERED = True
            logger.info("local trace recorder writing to %s", trace_dir())
            return True
        except Exception:  # noqa: BLE001 - tracing is dev observability only.
            logger.exception("failed to register local trace recorder")
            return False


__all__ = [
    "LocalTraceRecorder",
    "ensure_local_trace_processor",
    "local_tracing_enabled",
    "trace_dir",
    "trace_file_path",
]
