from pathlib import Path

import cv2
import numpy as np
import pytest

from augment_classifier.detector import TemplateMatcher


def test_detects_labeled_template_and_returns_its_box(tmp_path: Path) -> None:
    label_dir = tmp_path / "templates" / "jeweled_lotus"
    label_dir.mkdir(parents=True)
    template = np.array(
        [
            [0, 20, 80, 20, 0],
            [20, 120, 240, 120, 20],
            [80, 240, 255, 240, 80],
            [20, 120, 240, 120, 20],
            [0, 20, 80, 20, 0],
        ],
        dtype=np.uint8,
    )
    assert cv2.imwrite(str(label_dir / "standard.png"), template)
    image = np.zeros((30, 40), dtype=np.uint8)
    image[11:16, 17:22] = template

    detections = TemplateMatcher(tmp_path / "templates", threshold=0.99).detect(image)

    assert len(detections) == 1
    detection = detections[0]
    assert (detection.label, detection.x, detection.y) == ("jeweled_lotus", 17, 11)
    assert (detection.width, detection.height) == (5, 5)
    assert detection.confidence == pytest.approx(1.0)


def test_requires_at_least_one_labeled_template(tmp_path: Path) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    with pytest.raises(ValueError, match="No template images"):
        TemplateMatcher(template_dir)
