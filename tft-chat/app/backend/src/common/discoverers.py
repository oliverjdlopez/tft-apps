"""Deterministic filesystem discovery helpers."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path
from typing import TypeVar

from common.loaders import load_unique

T = TypeVar("T")


def discover_files(
    root: Path,
    patterns: Sequence[str],
    *,
    skip_names: Collection[str] = (),
) -> list[Path]:
    """Return sorted, unique files matching one or more root-relative globs."""

    if not root.is_dir():
        return []
    skipped = {name.casefold() for name in skip_names}
    paths = {
        path
        for pattern in patterns
        for path in root.glob(pattern)
        if path.is_file() and path.name.casefold() not in skipped
    }
    return sorted(paths)


def discover_unique(
    root: Path,
    patterns: Sequence[str],
    loader: Callable[[Path], T],
    *,
    identity: Callable[[T], str],
    skip_names: Collection[str] = (),
    on_error: Callable[[Path, Exception], None] | None = None,
    on_duplicate: Callable[[Path, T], None] | None = None,
    errors: tuple[type[Exception], ...] = (OSError, UnicodeError, ValueError),
) -> list[T]:
    """Discover and load unique files with the shared deterministic policy."""

    return load_unique(
        discover_files(root, patterns, skip_names=skip_names),
        loader,
        identity=identity,
        on_error=on_error,
        on_duplicate=on_duplicate,
        errors=errors,
    )


__all__ = ["discover_files", "discover_unique"]
