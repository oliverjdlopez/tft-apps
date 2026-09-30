"""Frozen adapter protocol and validation used by every independent algorithm."""

import json
from typing import Protocol
from pydantic import BaseModel
from .models import FrozenModel, FitResult
from .models import BoardObservation, BoardAssignment


class CompositionAdapter(Protocol):
    """Implement pure discovery and classification without IO or orchestration."""

    algorithm_id: str
    algorithm_version: str
    Parameters: type[BaseModel]

    def fit(
        self, boards: tuple[BoardObservation, ...], parameters: BaseModel, seed: int
    ) -> FitResult:
        """Fit a bounded, ordered snapshot without inspecting outcomes."""
        ...

    def classify(
        self, boards: tuple[BoardObservation, ...], model: FrozenModel
    ) -> tuple[BoardAssignment, ...]:
        """Classify independently under serialized thresholds and fitted state."""
        ...


def serialize_model(model: FrozenModel) -> str:
    """Produce canonical JSON; reject nonfinite and non-JSON diagnostic state."""
    return json.dumps(
        model.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def deserialize_model(value: str) -> FrozenModel:
    """Validate the shared serialized envelope before adapter-specific validation."""
    return FrozenModel.model_validate_json(value)
