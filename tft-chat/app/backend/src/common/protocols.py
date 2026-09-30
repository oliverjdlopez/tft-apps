"""Shared structural contracts for repository-backed providers."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, TypeVar


LoadedT = TypeVar("LoadedT", covariant=True)
SelectedT = TypeVar("SelectedT", covariant=True)


class Provider(Protocol[LoadedT, SelectedT]):
    """Common lifecycle for providers backed by discoverable repository data."""

    def load(self, path: Path, *, relative_to: Path | None = None) -> LoadedT: ...

    def discover(self) -> list[LoadedT]: ...

    def select(self, query: str, **kwargs: Any) -> list[SelectedT]: ...

    def render(self, selected: Sequence[SelectedT]) -> str: ...

    def select_and_render(self, query: str, **kwargs: Any) -> str: ...


__all__ = ["Provider"]
