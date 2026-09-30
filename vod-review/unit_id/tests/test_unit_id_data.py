from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from unit_id.data import (
    dataset_fingerprint,
    discover_images,
    inspect_images,
    inspect_unit_segmentation_dataset,
    load_record_image,
)


def test_discovery_is_recursive_and_content_addressed(tmp_path: Path):
    nested = tmp_path / "video"
    nested.mkdir()
    Image.new("RGB", (8, 6), "red").save(nested / "b.JPG")
    Image.new("RGB", (8, 6), "blue").save(tmp_path / "a.png")
    (tmp_path / "notes.txt").write_text("ignored")

    assert [path.name for path in discover_images(tmp_path)] == ["a.png", "b.JPG"]
    records = inspect_images(tmp_path)
    assert [record.relative_path for record in records] == ["a.png", "video/b.JPG"]
    assert all(len(record.sha256) == 64 for record in records)
    assert dataset_fingerprint(records) == dataset_fingerprint(records)


def test_inspection_reports_all_corrupt_images(tmp_path: Path):
    (tmp_path / "bad.png").write_text("not an image")

    with pytest.raises(ValueError, match="bad.png"):
        inspect_images(tmp_path)


def test_unit_segmentation_boxes_become_independent_crop_records(tmp_path: Path):
    images = tmp_path / "images" / "train"
    labels = tmp_path / "labels" / "train"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    image = Image.new("RGB", (100, 50), "red")
    ImageDraw.Draw(image).rectangle((50, 0, 99, 49), fill="blue")
    image.save(images / "board.png")
    (labels / "board.txt").write_text(
        "0 0.25 0.5 0.5 1.0\n0 0.75 0.5 0.5 1.0\n"
    )
    Image.new("RGB", (20, 20), "black").save(images / "negative.png")
    (labels / "negative.txt").write_text("")

    records = inspect_unit_segmentation_dataset(tmp_path)

    assert [record.relative_path for record in records] == [
        "images/train/board.png#box-001",
        "images/train/board.png#box-002",
    ]
    assert [load_record_image(record).size for record in records] == [(50, 50), (50, 50)]
    assert load_record_image(records[0]).getpixel((25, 25))[0] > 200
    assert load_record_image(records[1]).getpixel((25, 25))[2] > 200
    assert records[0].content_sha256 != records[1].content_sha256


def test_unit_segmentation_requires_matching_valid_labels(tmp_path: Path):
    images = tmp_path / "images" / "val"
    labels = tmp_path / "labels" / "val"
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    Image.new("RGB", (20, 20), "red").save(images / "missing.png")
    Image.new("RGB", (20, 20), "blue").save(images / "bad.png")
    (labels / "bad.txt").write_text("1 0.5 0.5 0.5 0.5\n")

    with pytest.raises(ValueError) as error:
        inspect_unit_segmentation_dataset(tmp_path)

    assert "missing corresponding" in str(error.value)
    assert "expected unit class 0" in str(error.value)
