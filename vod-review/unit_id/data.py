"""YOLO unit-detection dataset parsing and crop loading."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


@dataclass(frozen=True)
class ImageRecord:
    path: Path
    relative_path: str
    sha256: str
    crop_box: tuple[int, int, int, int] | None = None
    normalized_box: tuple[float, float, float, float] | None = None
    content_sha256: str | None = None


def discover_images(data_dir: Path) -> list[Path]:
    """Return supported image files recursively in stable relative-path order."""
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Crop directory does not exist: {data_dir}")
    return sorted(
        (
            path
            for path in data_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
        ),
        key=lambda path: path.relative_to(data_dir).as_posix(),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_images(data_dir: Path) -> list[ImageRecord]:
    """Validate every discovered image and return content-addressed records."""
    paths = discover_images(data_dir)
    if not paths:
        raise ValueError(f"No supported images found under {data_dir}")

    errors: list[str] = []
    records: list[ImageRecord] = []
    for path in paths:
        relative_path = path.relative_to(data_dir).as_posix()
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                image.convert("RGB").load()
        except (OSError, UnidentifiedImageError) as exc:
            errors.append(f"{relative_path}: {exc}")
            continue
        records.append(
            ImageRecord(
                path=path,
                relative_path=relative_path,
                sha256=sha256_file(path),
            )
        )
    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ValueError(f"Unreadable crop image(s):\n{details}")
    return records


def _crop_content_hash(image: Image.Image) -> str:
    digest = hashlib.sha256()
    digest.update(f"{image.mode}:{image.width}x{image.height}\0".encode("ascii"))
    digest.update(image.tobytes())
    return digest.hexdigest()


def load_record_image(record: ImageRecord) -> Image.Image:
    """Load the RGB image represented by a full-image or bounding-box record."""
    with Image.open(record.path) as image:
        rgb = image.convert("RGB")
        if record.crop_box is not None:
            rgb = rgb.crop(record.crop_box)
        return rgb.copy()


def inspect_unit_segmentation_dataset(data_dir: Path) -> list[ImageRecord]:
    """Turn every class-0 YOLO box into an unlabeled unit crop record."""
    images_dir = data_dir / "images"
    labels_dir = data_dir / "labels"
    if not images_dir.is_dir() or not labels_dir.is_dir():
        raise ValueError(
            f"Expected unit_segmentation YOLO directories at {images_dir} and {labels_dir}"
        )
    paths = discover_images(images_dir)
    if not paths:
        raise ValueError(f"No source images found under {images_dir}")

    errors: list[str] = []
    records: list[ImageRecord] = []
    for image_path in paths:
        image_relative = image_path.relative_to(images_dir)
        display_path = (Path("images") / image_relative).as_posix()
        label_path = (labels_dir / image_relative).with_suffix(".txt")
        if not label_path.is_file():
            errors.append(f"{display_path}: missing corresponding {label_path.relative_to(data_dir)}")
            continue
        try:
            label_lines = label_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            errors.append(f"{display_path}: could not read label file: {exc}")
            continue
        try:
            with Image.open(image_path) as source:
                image = source.convert("RGB")
                image.load()
        except (OSError, UnidentifiedImageError) as exc:
            errors.append(f"{display_path}: unreadable image: {exc}")
            continue

        image_hash = sha256_file(image_path)
        for line_number, raw_line in enumerate(label_lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            try:
                if len(parts) != 5:
                    raise ValueError("expected 5 fields")
                class_id = int(parts[0])
                x_center, y_center, width, height = (float(value) for value in parts[1:])
                if class_id != 0:
                    raise ValueError(f"expected unit class 0, found {class_id}")
                if not (
                    0 <= x_center <= 1
                    and 0 <= y_center <= 1
                    and 0 < width <= 1
                    and 0 < height <= 1
                ):
                    raise ValueError("coordinates must be normalized and dimensions positive")
                if (
                    x_center - width / 2 < -1e-6
                    or y_center - height / 2 < -1e-6
                    or x_center + width / 2 > 1 + 1e-6
                    or y_center + height / 2 > 1 + 1e-6
                ):
                    raise ValueError("bounding box extends outside the image")
            except ValueError as exc:
                errors.append(f"{label_path.relative_to(data_dir)}:{line_number}: {exc}")
                continue

            x0 = max(0, math.floor((x_center - width / 2) * image.width))
            y0 = max(0, math.floor((y_center - height / 2) * image.height))
            x1 = min(image.width, math.ceil((x_center + width / 2) * image.width))
            y1 = min(image.height, math.ceil((y_center + height / 2) * image.height))
            if x1 <= x0 or y1 <= y0:
                errors.append(
                    f"{label_path.relative_to(data_dir)}:{line_number}: box is empty in pixels"
                )
                continue
            normalized_box = (x_center, y_center, width, height)
            fingerprint = hashlib.sha256(
                f"{image_hash}\0{line_number}\0{line}".encode("utf-8")
            ).hexdigest()
            crop = image.crop((x0, y0, x1, y1))
            records.append(
                ImageRecord(
                    path=image_path,
                    relative_path=f"{display_path}#box-{line_number:03d}",
                    sha256=fingerprint,
                    crop_box=(x0, y0, x1, y1),
                    normalized_box=normalized_box,
                    content_sha256=_crop_content_hash(crop),
                )
            )

    if errors:
        details = "\n".join(f"  - {error}" for error in errors)
        raise ValueError(f"Invalid unit_segmentation dataset:\n{details}")
    if not records:
        raise ValueError(
            "The unit_segmentation dataset contains no unit boxes; empty label files "
            "are valid negative frames but cannot train unit identification"
        )
    return records


def dataset_fingerprint(records: list[ImageRecord]) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(record.relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(record.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()
