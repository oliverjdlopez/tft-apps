from pathlib import Path

import numpy as np
import pytest

from unit_id.artifact import UnitIdArtifact


def _artifact() -> UnitIdArtifact:
    return UnitIdArtifact(
        metadata={
            "cluster_ids": ["cluster_000", "cluster_001"],
            "backbone": "fake",
            "image_size": 32,
        },
        pca_mean=np.zeros(2, dtype=np.float32),
        pca_components=np.eye(2, dtype=np.float32),
        centroids=np.eye(2, dtype=np.float32),
    )


def test_ranked_predictions_return_every_label_and_margin():
    result = _artifact().ranked_predictions(np.asarray([[1.0, 0.2]], dtype=np.float32))[0]

    assert [item["label_id"] for item in result["candidates"]] == [
        "cluster_000",
        "cluster_001",
    ]
    assert [item["rank"] for item in result["candidates"]] == [1, 2]
    assert result["top_two_margin"] == pytest.approx(0.8 / np.sqrt(1.04))


def test_artifact_round_trip_reproduces_scores(tmp_path: Path):
    artifact = _artifact()
    embeddings = np.asarray([[0.2, 1.0], [1.0, 0.1]], dtype=np.float32)
    expected = artifact.score_embeddings(embeddings)

    artifact.save(tmp_path)
    loaded = UnitIdArtifact.load(tmp_path)

    assert np.allclose(loaded.score_embeddings(embeddings), expected)
    assert loaded.num_classes == 2
