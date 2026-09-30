"""Run YOLO unit bounding-box detection over a directory of images."""

from __future__ import annotations

import argparse
from pathlib import Path

from unit_segmentation.model import DEFAULT_MODEL, load_yolo


IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def discover_images(frames_dir: Path) -> list[Path]:
    if not frames_dir.is_dir():
        raise FileNotFoundError(f"Frames directory does not exist: {frames_dir}")
    return sorted(
        path
        for path in frames_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def run_inference(
    frames_dir: Path,
    output_dir: Path,
    model_path: str | Path = DEFAULT_MODEL,
    confidence: float = 0.25,
    image_size: int = 640,
    device: str | None = None,
) -> int:
    """Save annotated images and YOLO-format detection labels."""
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")

    image_paths = discover_images(frames_dir)
    if not image_paths:
        print(f"No supported images found under {frames_dir}")
        return 0

    model = load_yolo(model_path)
    for index, image_path in enumerate(image_paths, start=1):
        relative_path = image_path.relative_to(frames_dir)
        annotated_path = output_dir / "images" / relative_path
        label_path = (output_dir / "labels" / relative_path).with_suffix(".txt")
        annotated_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.parent.mkdir(parents=True, exist_ok=True)

        predict_options = {
            "source": str(image_path),
            "conf": confidence,
            "imgsz": image_size,
            "verbose": False,
        }
        if device is not None:
            predict_options["device"] = device
        result = model.predict(**predict_options)[0]
        result.save(filename=str(annotated_path))
        result.save_txt(str(label_path), save_conf=True)
        print(f"[{index}/{len(image_paths)}] {image_path} -> {annotated_path}")

    return len(image_paths)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect unit bounding boxes in frames")
    parser.add_argument("--frames-dir", type=Path, default=Path("frames"))
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--image-size", type=int, default=640)
    parser.add_argument("--device", help="Ultralytics device, such as cpu, 0, or mps")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = run_inference(
        frames_dir=args.frames_dir,
        output_dir=args.output_dir,
        model_path=args.model,
        confidence=args.confidence,
        image_size=args.image_size,
        device=args.device,
    )
    print(f"Processed {count} image(s)")


if __name__ == "__main__":
    main()
