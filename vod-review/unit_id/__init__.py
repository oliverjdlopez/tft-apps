"""Unsupervised closed-set unit identity discovery and inference."""

from unit_id.artifact import UnitIdArtifact

__all__ = ["UnitIdArtifact", "UnitIdentifier"]


def __getattr__(name: str):
    if name == "UnitIdentifier":
        from unit_id.predict import UnitIdentifier

        return UnitIdentifier
    raise AttributeError(name)
