"""Shared service helpers."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from common.paths import find_repo_root
from common.serialization import write_json_lines

_CHAT_TIMING_LOCK = threading.Lock()


def write_chat_timing(record: Mapping[str, Any]) -> None:
    """Append one chat timing record to the repository profiles directory.

    Args:
        record: Timing fields for one `/api/chat` response.

    Profiling is diagnostic only, so filesystem failures must not affect chat.
    """
    path = find_repo_root() / "profiles" / "chat_timing.jsonl"
    try:
        with _CHAT_TIMING_LOCK:
            write_json_lines(path, [record], append=True, flush=True)
    except OSError:
        return


__all__ = ["write_chat_timing"]
