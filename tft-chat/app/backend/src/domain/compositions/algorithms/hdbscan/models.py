"""Validated HDBSCAN settings and portable reference membership state."""

from dataclasses import dataclass
from typing import Literal

import numpy as np

from pydantic import Field, model_validator

from ...models import BoardObservation, CompositionModel


@dataclass(frozen=True)
class DiscoveryResult:
    """Carry native labels and either CPU distances or GPU-fit feature vectors.

    GPU fitting retains only the feature matrix for bounded medoid selection;
    it never requires an application-owned population-square distance matrix.
    """

    labels: np.ndarray
    strengths: np.ndarray
    persistence: np.ndarray
    backend: Literal["cpu", "cuda", "not_required"]
    distances: np.ndarray | None = None
    vectors: np.ndarray | None = None
    warning: str | None = None


class Parameters(CompositionModel):
    """Configure density discovery and the separate frozen reference classifier."""

    min_cluster_size: int = Field(default=5, ge=2, strict=True)
    min_samples: int = Field(default=3, ge=1, strict=True)
    cluster_selection_method: Literal["eom", "leaf"] = "eom"
    cluster_selection_epsilon: float = Field(default=0.0, ge=0)
    allow_single_cluster: bool = False
    rejection_distance: float = Field(default=2.0, ge=0)
    ambiguity_margin: float = Field(default=0.05, ge=0)


class FrozenCluster(CompositionModel):
    """Keep all native cluster references and density persistence for one family."""

    family_id: str = Field(min_length=1)
    persistence: float = Field(ge=0, le=1)
    references: tuple[BoardObservation, ...] = Field(min_length=1)


class State(CompositionModel):
    """Validate JSON-only fitted state without pickled estimators or prediction data."""

    state_version: Literal["hdbscan.references.v1"] = "hdbscan.references.v1"
    matching_policy: Literal["nearest_native_reference.v1"] = (
        "nearest_native_reference.v1"
    )
    seed: int = Field(strict=True)
    clusters: tuple[FrozenCluster, ...]
    noise_observation_ids: tuple[str, ...]

    @model_validator(mode="after")
    def unique_references(self):
        """Reject duplicated memberships and noise overlapping any frozen cluster."""
        families = [cluster.family_id for cluster in self.clusters]
        references = [
            board.observation_id
            for cluster in self.clusters
            for board in cluster.references
        ]
        all_ids = references + list(self.noise_observation_ids)
        if len(set(families)) != len(families) or len(set(all_ids)) != len(all_ids):
            raise ValueError(
                "HDBSCAN state contains duplicate families or observations"
            )
        if any(
            not board.units for cluster in self.clusters for board in cluster.references
        ):
            raise ValueError("HDBSCAN references require observed units")
        return self
