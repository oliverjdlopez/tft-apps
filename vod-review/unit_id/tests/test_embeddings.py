from pathlib import Path

import numpy as np

from unit_id.data import ImageRecord
from unit_id.embeddings import extract_with_cache


class FakeEmbedder:
    backbone = "fake"
    image_size = 32

    def __init__(self):
        self.calls: list[list[str]] = []

    def extract(self, paths: list[Path], batch_size: int) -> np.ndarray:
        self.calls.append([path.name for path in paths])
        return np.asarray(
            [[len(path.name), index + 1] for index, path in enumerate(paths)],
            dtype=np.float32,
        )


class FakeCropEmbedder:
    backbone = "fake-crops"
    image_size = 32

    def __init__(self):
        self.calls: list[list[tuple[int, int, int, int] | None]] = []

    def extract_records(
        self, records: list[ImageRecord], batch_size: int
    ) -> np.ndarray:
        self.calls.append([record.crop_box for record in records])
        return np.asarray(
            [[record.crop_box[0] + 1, record.crop_box[2] + 1] for record in records],
            dtype=np.float32,
        )


def test_embedding_cache_reuses_only_unchanged_records(tmp_path: Path):
    records = [
        ImageRecord(tmp_path / "a.png", "a.png", "hash-a"),
        ImageRecord(tmp_path / "bb.png", "bb.png", "hash-b"),
    ]
    embedder = FakeEmbedder()
    cache = tmp_path / "cache.npz"

    first = extract_with_cache(records, embedder, cache, batch_size=8)
    second = extract_with_cache(records, embedder, cache, batch_size=8)
    changed = [records[0], ImageRecord(tmp_path / "bb.png", "bb.png", "new-hash")]
    third = extract_with_cache(changed, embedder, cache, batch_size=8)

    assert first.shape == second.shape == third.shape == (2, 2)
    assert embedder.calls == [["a.png", "bb.png"], ["bb.png"]]
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0)


def test_embedding_cache_extracts_bounding_box_records(tmp_path: Path):
    records = [
        ImageRecord(
            tmp_path / "frame.png",
            "images/train/frame.png#box-001",
            "box-a",
            crop_box=(0, 0, 10, 10),
        ),
        ImageRecord(
            tmp_path / "frame.png",
            "images/train/frame.png#box-002",
            "box-b",
            crop_box=(10, 0, 20, 10),
        ),
    ]
    embedder = FakeCropEmbedder()

    result = extract_with_cache(records, embedder, tmp_path / "cache.npz", 8)

    assert result.shape == (2, 2)
    assert embedder.calls == [[(0, 0, 10, 10), (10, 0, 20, 10)]]
