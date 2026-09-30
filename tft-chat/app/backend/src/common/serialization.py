"""JSON conversion, preview, and JSON Lines helpers."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Recursively convert arbitrary values into JSON-compatible data.

    Args:
        value: Value to convert, including mappings, model instances, and
            database-native scalar values.

    Returns:
        A value containing only JSON-compatible scalar, sequence, and mapping
        types.
    """

    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json")
        except TypeError:
            return to_jsonable(value.model_dump())
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(item) for item in value]
    try:
        json.dumps(value)
    except (TypeError, ValueError):
        return str(value)
    return value


def model_jsonable(value: Any) -> Any:
    """Convert a value for model-visible output with two-decimal numbers.

    Args:
        value: Tool result or other structured value that may be shown to a
            language model.

    Returns:
        JSON-compatible data where every floating-point number is rounded to
        at most two decimal places. Integer counts and booleans are preserved.
    """

    return _round_model_numbers(to_jsonable(value))


def _round_model_numbers(value: Any) -> Any:
    """Recursively round numeric leaves in already JSON-compatible data.

    Args:
        value: JSON-compatible scalar, sequence, or mapping.

    Returns:
        The same data shape with floating-point leaves rounded to two places.
    """

    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return round(value, 2)
    if isinstance(value, Mapping):
        return {key: _round_model_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_model_numbers(item) for item in value]
    return value


def strict_jsonable(value: Any) -> Any:
    """Round-trip a value through JSON, stringifying unsupported leaves."""

    return json.loads(json.dumps(value, default=str))


def render_json_preview(
    value: Any,
    *,
    max_chars: int,
    indent: int = 2,
) -> str:
    """Render JSON and append an ellipsis when it exceeds ``max_chars``."""

    text = json.dumps(to_jsonable(value), ensure_ascii=False, indent=indent)
    return text if len(text) <= max_chars else f"{text[:max_chars].rstrip()}\n..."


def truncate_json(value: Any, *, max_bytes: int) -> dict[str, Any]:
    """Return a structured full value or bounded pretty-JSON preview."""

    converted = strict_jsonable(value)
    text = json.dumps(converted, indent=2)
    total = len(text)
    if total <= max_bytes:
        return {"json": value, "truncated": False, "total_chars": total}
    return {
        "preview": text[:max_bytes] + "\n... [truncated]",
        "truncated": True,
        "total_chars": total,
        "top_level_keys": list(value.keys()) if isinstance(value, dict) else None,
        "length": len(value) if isinstance(value, (list, dict)) else None,
    }


def read_json_lines(path: Path) -> list[Any]:
    """Read nonblank JSON Lines records from ``path``."""

    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def write_json_lines(
    path: Path,
    rows: Iterable[Any],
    *,
    append: bool = False,
    flush: bool = False,
    sort_keys: bool = False,
) -> None:
    """Write JSON Lines records, creating the destination directory."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a" if append else "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(
                json.dumps(
                    to_jsonable(row),
                    ensure_ascii=False,
                    sort_keys=sort_keys,
                    default=str,
                )
            )
            handle.write("\n")
            if flush:
                handle.flush()


__all__ = [
    "model_jsonable",
    "read_json_lines",
    "render_json_preview",
    "strict_jsonable",
    "to_jsonable",
    "truncate_json",
    "write_json_lines",
]
