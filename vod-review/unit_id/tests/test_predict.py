from pathlib import Path

import numpy as np

from unit_id.artifact import UnitIdArtifact
from unit_id.predict import UnitIdentifier


class FakeEmbedder:
    backbone = "fake"
    image_size = 32

    def extract(self, paths: list[Path], batch_size: int) -> np.ndarray:
        return np.asarray([[1.0, 0.1] for _path in paths], dtype=np.float32)

    def extract_images(self, images: list[object], batch_size: int) -> np.ndarray:
        return np.asarray([[0.1, 1.0] for _image in images], dtype=np.float32)


def test_identifier_returns_ranked_paths_without_loading_dinov2(tmp_path: Path):
    UnitIdArtifact(
        metadata={
            "cluster_ids": ["cluster_000", "cluster_001"],
            "backbone": "fake",
            "image_size": 32,
        },
        pca_mean=np.zeros(2, dtype=np.float32),
        pca_components=np.eye(2, dtype=np.float32),
        centroids=np.eye(2, dtype=np.float32),
    ).save(tmp_path)

    identifier = UnitIdentifier(tmp_path, embedder=FakeEmbedder())
    result = identifier.predict_paths([Path("crop.png")], top_k=1)

    assert result[0]["path"] == "crop.png"
    assert result[0]["candidates"] == [
        {
            "label_id": "cluster_000",
            "rank": 1,
            "cosine_similarity": result[0]["candidates"][0]["cosine_similarity"],
        }
    ]
    assert result[0]["top_two_margin"] is not None

    in_memory = identifier.predict_batch([np.zeros((8, 8, 3), dtype=np.uint8)])
    assert in_memory[0]["candidates"][0]["label_id"] == "cluster_001"
