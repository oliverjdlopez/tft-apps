"""Train YOLO to detect unit bounding boxes."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from unit_segmentation.model import DEFAULT_MODEL, load_yolo


def train_detector(
    data: Path,
    model: str | Path = DEFAULT_MODEL,
    epochs: int = 100,
    image_size: int = 640,
    batch_size: int = 16,
    project: Path = Path("artifacts/unit-detection"),
    run_name: str = "train",
    device: str | None = None,
) -> Any:
    """Train a YOLO detection model from a standard YOLO dataset YAML file."""
    if not data.is_file():
        raise FileNotFoundError(f"Dataset YAML does not exist: {data}")
    if epochs < 1:
        raise ValueError("epochs must be at least 1")
    if image_size < 1:
        raise ValueError("image_size must be at least 1")

    detector = load_yolo(model)
    options: dict[str, Any] = {
        "data": str(data.resolve()),
        "task": "detect",
        "epochs": epochs,
        "imgsz": image_size,
        "batch": batch_size,
        "project": str(project),
        "name": run_name,
    }
    if device is not None:
        options["device"] = device
    return detector.train(**options)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train YOLO unit bounding-box detection")
    parser.add_argument("--data", type=Path, required=True, help="YOLO dataset YAML")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--project", type=Path, default=Path("artifacts/unit-detection"))
    parser.add_argument("--name", default="train")
    parser.add_argument("--device", help="Ultralytics device, such as cpu, 0, or mps")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    train_detector(
        data=args.data,
        model=args.model,
        epochs=args.epochs,
        image_size=args.image_size,
        batch_size=args.batch_size,
        project=args.project,
        run_name=args.name,
        device=args.device,
    )


if __name__ == "__main__":
    main()
