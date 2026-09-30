import json
from pathlib import Path

import numpy as np
from PIL import Image

from unit_id.data import ImageRecord
from unit_id.train import train_discovery


class FakeEmbedder:
    backbone = "fake"
    image_size = 32

    def extract_records(
        self, records: list[ImageRecord], batch_size: int
    ) -> np.ndarray:
        rows = []
        for record in records:
            cluster, sample = (
                int(part)
                for part in record.path.stem.removeprefix("unit-").split("-")
            )
            row = np.zeros(6, dtype=np.float32)
            row[cluster] = 1.0
            row[3 + cluster] = sample * 0.01
            rows.append(row)
        return np.stack(rows)


def test_training_writes_portable_artifact_assignments_and_audit(tmp_path: Path):
    data_dir = tmp_path / "unit_segmentation"
    images = data_dir / "images" / "train"
    labels = data_dir / "labels" / "train"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    for cluster in range(3):
        for sample in range(4):
            Image.new(
                "RGB",
                (18 + sample, 14),
                (cluster * 80, sample * 20, 100),
            ).save(images / f"unit-{cluster}-{sample}.png")
            (labels / f"unit-{cluster}-{sample}.txt").write_text(
                "0 0.5 0.5 1.0 1.0\n"
            )
    output = tmp_path / "artifact"

    artifact = train_discovery(
        data_dir,
        output,
        3,
        backbone="fake",
        image_size=32,
        stability_runs=1,
        examples_per_view=2,
        embedder=FakeEmbedder(),
    )

    assert artifact.num_classes == 3
    assert (output / "metadata.json").is_file()
    assert (output / "model.npz").is_file()
    assignment_lines = (output / "assignments.jsonl").read_text().splitlines()
    assert len(assignment_lines) == 12
    assert len(json.loads(assignment_lines[0])["candidates"]) == 3
    assert json.loads(assignment_lines[0])["bounding_box"] == {
        "height": 1.0,
        "width": 1.0,
        "x_center": 0.5,
        "y_center": 0.5,
    }
    assert (output / "audit" / "index.html").is_file()
    assert (output / "audit" / "report.json").is_file()
