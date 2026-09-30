import numpy as np
import pytest

from unit_id.clustering import discover_clusters


def _separated_embeddings() -> tuple[np.ndarray, list[str]]:
    generator = np.random.default_rng(4)
    centers = np.eye(3, 8, dtype=np.float32)
    rows = []
    paths = []
    for cluster, center in enumerate(centers):
        for sample in range(12):
            rows.append(center + generator.normal(0, 0.025, size=8))
            paths.append(f"c{cluster}/sample-{sample:02d}.png")
    return np.asarray(rows, dtype=np.float32), paths


def test_discovery_finds_exact_n_stable_clusters():
    embeddings, paths = _separated_embeddings()

    first = discover_clusters(embeddings, paths, 3, seed=7, stability_runs=2)
    second = discover_clusters(embeddings, paths, 3, seed=7, stability_runs=2)

    assert np.array_equal(first.assignments, second.assignments)
    assert len(np.unique(first.assignments)) == 3
    assert first.centroids.shape == (3, first.pca_components.shape[0])
    assert first.metrics["cluster_sizes"] == [12, 12, 12]
    assert first.metrics["bootstrap_adjusted_rand_mean"] == pytest.approx(1.0)


def test_discovery_rejects_too_few_distinct_samples():
    embeddings = np.asarray([[1, 0], [1, 0], [0, 1]], dtype=np.float32)

    with pytest.raises(ValueError, match="distinct embeddings"):
        discover_clusters(embeddings, ["a", "b", "c"], 3)
