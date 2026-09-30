from pathlib import Path

from text_detection import train


class FakeDetector:
    def __init__(self):
        self.options = None

    def train(self, **options):
        self.options = options
        return "trained"


def test_train_detector_uses_detection_task(monkeypatch, tmp_path: Path):
    data = tmp_path / "data.yaml"
    data.write_text("names: [text]\n")
    detector = FakeDetector()
    monkeypatch.setattr(train, "load_yolo", lambda _model: detector)

    result = train.train_detector(data, epochs=2, image_size=960, batch_size=4)

    assert result == "trained"
    assert detector.options["task"] == "detect"
    assert detector.options["data"] == str(data.resolve())
    assert detector.options["epochs"] == 2
    assert detector.options["imgsz"] == 960
    assert detector.options["batch"] == 4
    assert detector.options["exist_ok"] is True
