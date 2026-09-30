"""Filesystem path helpers."""

from __future__ import annotations

from pathlib import Path


def find_repo_root(start: Path | None = None) -> Path:
    """Find the nearest ancestor containing ``pyproject.toml``."""

    origin = (start or Path(__file__)).resolve()
    candidates = (origin, *origin.parents) if origin.is_dir() else origin.parents
    for parent in candidates:
        if (parent / "pyproject.toml").exists():
            return parent
    raise FileNotFoundError(f"could not find repository root from {origin}")


def display_path(path: Path, *, relative_to: Path) -> str:
    """Render ``path`` relative to a base when it is contained by that base."""

    try:
        return str(path.relative_to(relative_to))
    except ValueError:
        return str(path)


__all__ = ["display_path", "find_repo_root"]
