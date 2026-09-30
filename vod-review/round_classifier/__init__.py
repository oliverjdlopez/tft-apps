"""Training and inference utilities for the round classifier."""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .model import RoundClassifier

__all__ = ["RoundClassifier"]


def __getattr__(name: str) -> Any:
    if name == "RoundClassifier":
        from .model import RoundClassifier

        return RoundClassifier
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
