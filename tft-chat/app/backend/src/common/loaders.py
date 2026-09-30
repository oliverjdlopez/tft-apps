"""Deterministic loading helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def load_unique(
    paths: Iterable[Path],
    loader: Callable[[Path], T],
    *,
    identity: Callable[[T], str],
    on_error: Callable[[Path, Exception], None] | None = None,
    on_duplicate: Callable[[Path, T], None] | None = None,
    errors: tuple[type[Exception], ...] = (OSError, UnicodeError, ValueError),
) -> list[T]:
    """Load discovered files deterministically, skipping invalid or duplicate items."""

    loaded: list[T] = []
    seen: set[str] = set()
    for path in paths:
        try:
            item = loader(path)
        except errors as exc:
            if on_error is not None:
                on_error(path, exc)
            continue
        key = identity(item)
        if key in seen:
            if on_duplicate is not None:
                on_duplicate(path, item)
            continue
        seen.add(key)
        loaded.append(item)
    return loaded


__all__ = ["load_unique"]
