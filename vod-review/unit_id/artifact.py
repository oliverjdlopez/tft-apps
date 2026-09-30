"""Portable unit-discovery artifact serialization and scoring."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


ARTIFACT_VERSION = 1
METADATA_FILE = "metadata.json"
ARRAYS_FILE = "model.npz"


def normalize_rows(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float32)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("Cannot normalize a zero-length vector")
    return values / norms


@dataclass
class UnitIdArtifact:
    metadata: dict[str, Any]
    pca_mean: np.ndarray
    pca_components: np.ndarray
    centroids: np.ndarray

    @property
    def cluster_ids(self) -> list[str]:
        return [str(label) for label in self.metadata["cluster_ids"]]

    @property
    def num_classes(self) -> int:
        return len(self.cluster_ids)

    def project(self, embeddings: np.ndarray) -> np.ndarray:
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[1] != self.pca_mean.shape[0]:
            raise ValueError(
                f"Expected embeddings shaped (n, {self.pca_mean.shape[0]}), "
                f"got {embeddings.shape}"
            )
        embeddings = normalize_rows(embeddings)
        projected = (embeddings - self.pca_mean) @ self.pca_components.T
        return normalize_rows(projected)

    def score_embeddings(self, embeddings: np.ndarray) -> np.ndarray:
        """Return cosine similarities in canonical cluster-ID order."""
        return self.project(embeddings) @ self.centroids.T

    def ranked_predictions(
        self, embeddings: np.ndarray, top_k: int | None = None
    ) -> list[dict[str, Any]]:
        if top_k is not None and not 1 <= top_k <= self.num_classes:
            raise ValueError(f"top_k must be between 1 and {self.num_classes}")
        scores = self.score_embeddings(embeddings)
        limit = self.num_classes if top_k is None else top_k
        predictions: list[dict[str, Any]] = []
        for row in scores:
            ordering = np.argsort(-row, kind="stable")
            candidates = [
                {
                    "label_id": self.cluster_ids[int(index)],
                    "rank": rank,
                    "cosine_similarity": float(row[index]),
                }
                for rank, index in enumerate(ordering[:limit], start=1)
            ]
            margin = float(row[ordering[0]] - row[ordering[1]]) if len(ordering) > 1 else None
            predictions.append({"candidates": candidates, "top_two_margin": margin})
        return predictions

    def save(self, artifact_dir: Path) -> None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        metadata = dict(self.metadata)
        metadata["artifact_version"] = ARTIFACT_VERSION
        _write_text_atomic(artifact_dir / METADATA_FILE, json.dumps(metadata, indent=2) + "\n")
        _write_npz_atomic(
            artifact_dir / ARRAYS_FILE,
            pca_mean=np.asarray(self.pca_mean, dtype=np.float32),
            pca_components=np.asarray(self.pca_components, dtype=np.float32),
            centroids=np.asarray(self.centroids, dtype=np.float32),
        )

    @classmethod
    def load(cls, artifact_dir: Path) -> "UnitIdArtifact":
        try:
            metadata = json.loads((artifact_dir / METADATA_FILE).read_text(encoding="utf-8"))
            with np.load(artifact_dir / ARRAYS_FILE, allow_pickle=False) as arrays:
                artifact = cls(
                    metadata=metadata,
                    pca_mean=arrays["pca_mean"].astype(np.float32),
                    pca_components=arrays["pca_components"].astype(np.float32),
                    centroids=arrays["centroids"].astype(np.float32),
                )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Invalid unit-ID artifact: {artifact_dir}") from exc
        artifact._validate()
        return artifact

    def _validate(self) -> None:
        if self.metadata.get("artifact_version") != ARTIFACT_VERSION:
            raise RuntimeError("Unsupported unit-ID artifact version")
        if self.pca_mean.ndim != 1 or self.pca_components.ndim != 2 or self.centroids.ndim != 2:
            raise RuntimeError("Unit-ID artifact contains invalid array dimensions")
        if self.pca_components.shape[1] != self.pca_mean.shape[0]:
            raise RuntimeError("Unit-ID PCA arrays are incompatible")
        if self.centroids.shape != (self.num_classes, self.pca_components.shape[0]):
            raise RuntimeError("Unit-ID centroids are incompatible with metadata or PCA")
        if not np.allclose(np.linalg.norm(self.centroids, axis=1), 1.0, atol=1e-4):
            raise RuntimeError("Unit-ID centroids are not normalized")


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_npz_atomic(path: Path, **arrays: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".npz", dir=path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        np.savez_compressed(temporary, **arrays)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
