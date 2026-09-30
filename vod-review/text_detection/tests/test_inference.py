from pathlib import Path

import pytest

from text_detection import inference


def test_discover_images_is_recursive_and_filters_non_images(tmp_path: Path):
    nested = tmp_path / "screens"
    nested.mkdir()
    (nested / "b.JPG").write_bytes(b"image")
    (nested / "a.png").write_bytes(b"image")
    (nested / "notes.txt").write_text("ignore")

    assert [path.name for path in inference.discover_images(tmp_path)] == ["a.png", "b.JPG"]


def test_confidence_must_be_a_probability(tmp_path: Path):
    with pytest.raises(ValueError, match="between 0 and 1"):
        inference.run_inference(tmp_path, tmp_path / "output", confidence=-0.1)


def test_inference_saves_box_visualization_and_labels(monkeypatch, tmp_path: Path):
    images_dir = tmp_path / "frames"
    image_path = images_dir / "vod" / "frame.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"image")
    calls = []

    class FakeResult:
        def save(self, **options):
            calls.append(("image", options))

        def save_txt(self, path, **options):
            calls.append(("labels", path, options))

    class FakeModel:
        def predict(self, **options):
            calls.append(("predict", options))
            return [FakeResult()]

    monkeypatch.setattr(inference, "load_yolo", lambda _model: FakeModel())
    output_dir = tmp_path / "output"

    assert inference.run_inference(images_dir, output_dir) == 1
    assert calls[0][0] == "predict"
    assert calls[1] == (
        "image",
        {"filename": str(output_dir / "images" / "vod" / "frame.png")},
    )
    assert calls[2] == (
        "labels",
        str(output_dir / "labels" / "vod" / "frame.txt"),
        {"save_conf": True},
    )
