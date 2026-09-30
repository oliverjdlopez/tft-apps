"""Small adapters for values that may be mappings or attribute objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def field_value(value: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or object, returning ``default`` if absent."""

    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


__all__ = ["field_value"]
