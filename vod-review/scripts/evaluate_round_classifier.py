from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(REPOSITORY_ROOT / "artifacts/paddlex"))

import numpy as np
from PIL import Image

from round_classifier.ocr import detect_and_recognize_round_images


DEFAULT_DATA_DIR = Path("data/datasets/round_classifier/train")
DEFAULT_OUTPUT = Path("round_classifier.json")
IMAGE_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate PaddleOCR against the labeled round-classifier training set"
    )
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--minimum-confidence", type=float, default=0.50)
    return parser.parse_args()


def discover_images(data_dir: Path) -> list[Path]:
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Round-classifier training directory not found: {data_dir}")
    return sorted(
        path
        for path in data_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def load_rgb(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")).copy()


def evaluate(data_dir: Path, batch_size: int, minimum_confidence: float) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch size must be at least 1")
    if not 0.0 <= minimum_confidence <= 1.0:
        raise ValueError("minimum confidence must be between 0 and 1")
    image_paths = discover_images(data_dir)
    if not image_paths:
        raise RuntimeError(f"No images found under {data_dir}")

    class_names = sorted(path.name for path in data_dir.iterdir() if path.is_dir())
    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    for offset in range(0, len(image_paths), batch_size):
        paths = image_paths[offset : offset + batch_size]
        crops = [load_rgb(path) for path in paths]
        predictions = detect_and_recognize_round_images(
            [Image.fromarray(crop) for crop in crops],
            class_names,
            minimum_confidence=minimum_confidence,
        )
        for path, prediction in zip(paths, predictions, strict=True):
            selected = prediction["prediction"]
            label = selected["parsed_label"] if selected is not None else None
            expected = path.parent.name
            results.append(
                {
                    "image": str(path.relative_to(REPOSITORY_ROOT)),
                    "expected": expected,
                    "predicted": label,
                    "raw_ocr_text": selected["raw_ocr_text"] if selected else None,
                    "ocr_confidence": selected["ocr_confidence"] if selected else None,
                    "yolo_bbox": selected["bbox"] if selected else None,
                    "yolo_confidence": (
                        selected["detection_confidence"] if selected else None
                    ),
                    "detected_text_boxes": len(prediction["candidates"]),
                    "candidates": prediction["candidates"],
                    "correct": label == expected,
                }
            )
        print(f"[model] {min(offset + batch_size, len(image_paths))}/{len(image_paths)}")

    correct = sum(result["correct"] for result in results)
    predicted = sum(result["predicted"] is not None for result in results)
    return {
        "passed": True,
        "minimum_confidence": minimum_confidence,
        "total": len(results),
        "correct": correct,
        "accuracy": correct / len(results),
        "ocr_predictions": predicted,
        "ocr_coverage": predicted / len(results),
        "accuracy_when_predicted": correct / predicted if predicted else 0.0,
        "unresolved_predictions": len(results) - predicted,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "results": results,
    }


def main() -> int:
    args = parse_args()
    output_path = args.output.resolve()
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_dir": str(args.data_dir),
    }
    try:
        report["round_classifier"] = evaluate(
            args.data_dir.resolve(), args.batch_size, args.minimum_confidence
        )
    except Exception as exc:
        report["round_classifier"] = {
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(f"[model] FAIL: {exc}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0 if report["round_classifier"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
