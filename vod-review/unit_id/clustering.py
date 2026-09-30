"""Exact-N discovery over pretrained visual embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from unit_id.artifact import normalize_rows


@dataclass
class DiscoveryResult:
    pca_mean: np.ndarray
    pca_components: np.ndarray
    projected: np.ndarray
    centroids: np.ndarray
    assignments: np.ndarray
    similarities: np.ndarray
    metrics: dict[str, Any]


def _fit_kmeans(values: np.ndarray, num_classes: int, seed: int, n_init: int) -> tuple[np.ndarray, np.ndarray]:
    try:
        from sklearn.cluster import KMeans
    except ImportError as exc:
        raise RuntimeError("scikit-learn is required for unit discovery; run `uv sync`") from exc

    model = KMeans(
        n_clusters=num_classes,
        init="k-means++",
        n_init=n_init,
        random_state=seed,
        algorithm="lloyd",
    ).fit(values)
    centroids = normalize_rows(model.cluster_centers_)
    assignments = (values @ centroids.T).argmax(axis=1)

    # Recompute means after cosine reassignment so saved centroids match inference.
    for _ in range(20):
        if len(np.unique(assignments)) != num_classes:
            raise ValueError("Clustering produced an empty class; add more varied crops or reduce N")
        centroids = normalize_rows(
            np.stack([values[assignments == index].mean(axis=0) for index in range(num_classes)])
        )
        updated = (values @ centroids.T).argmax(axis=1)
        if np.array_equal(updated, assignments):
            break
        assignments = updated
    return assignments.astype(np.int64), centroids.astype(np.float32)


def _canonicalize(
    paths: list[str], values: np.ndarray, assignments: np.ndarray, centroids: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    representative_paths: list[tuple[str, int]] = []
    for cluster in range(centroids.shape[0]):
        members = np.flatnonzero(assignments == cluster)
        similarities = values[members] @ centroids[cluster]
        representative = members[int(np.argmax(similarities))]
        representative_paths.append((paths[representative], cluster))
    old_order = [cluster for _path, cluster in sorted(representative_paths)]
    old_to_new = {old: new for new, old in enumerate(old_order)}
    canonical_assignments = np.asarray([old_to_new[int(old)] for old in assignments], dtype=np.int64)
    return canonical_assignments, centroids[old_order]


def discover_clusters(
    embeddings: np.ndarray,
    paths: list[str],
    num_classes: int,
    *,
    pca_dimensions: int = 128,
    seed: int = 0,
    n_init: int = 20,
    stability_runs: int = 5,
) -> DiscoveryResult:
    """Fit PCA and normalized k-means, then measure resampling stability."""
    embeddings = normalize_rows(embeddings)
    if embeddings.ndim != 2 or embeddings.shape[0] != len(paths):
        raise ValueError("Expected one path for every embedding")
    if num_classes < 2:
        raise ValueError("num_classes must be at least 2")
    if embeddings.shape[0] < num_classes:
        raise ValueError(f"Need at least {num_classes} images, found {embeddings.shape[0]}")
    if len(np.unique(embeddings, axis=0)) < num_classes:
        raise ValueError(f"Need at least {num_classes} distinct embeddings")
    if pca_dimensions < 1 or n_init < 1 or stability_runs < 0:
        raise ValueError("PCA dimensions and n_init must be positive; stability_runs cannot be negative")

    try:
        from sklearn.decomposition import PCA
        from sklearn.metrics import adjusted_rand_score, silhouette_score
    except ImportError as exc:
        raise RuntimeError("scikit-learn is required for unit discovery; run `uv sync`") from exc

    component_count = min(pca_dimensions, embeddings.shape[0] - 1, embeddings.shape[1])
    pca = PCA(n_components=component_count, whiten=False, svd_solver="full")
    projected = normalize_rows(pca.fit_transform(embeddings))
    if len(np.unique(projected, axis=0)) < num_classes:
        raise ValueError(f"PCA output contains fewer than {num_classes} distinct samples")

    assignments, centroids = _fit_kmeans(projected, num_classes, seed, n_init)
    assignments, centroids = _canonicalize(paths, projected, assignments, centroids)
    similarities = projected @ centroids.T

    stability: list[float] = []
    generator = np.random.default_rng(seed)
    sample_size = max(num_classes, round(len(projected) * 0.8))
    for run in range(stability_runs):
        subset = np.sort(generator.choice(len(projected), size=sample_size, replace=False))
        try:
            _subset_assignments, alternate_centroids = _fit_kmeans(
                projected[subset], num_classes, seed + run + 1, n_init
            )
        except ValueError:
            stability.append(0.0)
            continue
        alternate_all = (projected @ alternate_centroids.T).argmax(axis=1)
        stability.append(float(adjusted_rand_score(assignments, alternate_all)))

    assigned_scores = similarities[np.arange(len(assignments)), assignments]
    sorted_scores = np.sort(similarities, axis=1)
    margins = sorted_scores[:, -1] - sorted_scores[:, -2]
    cluster_sizes = np.bincount(assignments, minlength=num_classes)
    silhouette = (
        float(silhouette_score(projected, assignments, metric="cosine"))
        if len(projected) > num_classes
        else None
    )
    metrics: dict[str, Any] = {
        "silhouette_cosine": silhouette,
        "bootstrap_adjusted_rand": stability,
        "bootstrap_adjusted_rand_mean": float(np.mean(stability)) if stability else None,
        "cluster_sizes": cluster_sizes.tolist(),
        "assigned_similarity": {
            "minimum": float(assigned_scores.min()),
            "mean": float(assigned_scores.mean()),
            "maximum": float(assigned_scores.max()),
        },
        "top_two_margin": {
            "minimum": float(margins.min()),
            "mean": float(margins.mean()),
            "maximum": float(margins.max()),
        },
        "pca_dimensions": component_count,
        "pca_explained_variance_ratio": float(pca.explained_variance_ratio_.sum()),
    }
    return DiscoveryResult(
        pca_mean=pca.mean_.astype(np.float32),
        pca_components=pca.components_.astype(np.float32),
        projected=projected.astype(np.float32),
        centroids=centroids.astype(np.float32),
        assignments=assignments,
        similarities=similarities.astype(np.float32),
        metrics=metrics,
    )
