"""Ultralytics YOLO model loading for unit bounding-box detection."""

from __future__ import annotations

from pathlib import Path
from typing import Any


DEFAULT_MODEL = "yolo26n.pt"


def load_yolo(model: str | Path = DEFAULT_MODEL) -> Any:
    """Load a YOLO detection checkpoint or pretrained model name."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is required for unit detection; run `uv sync` first"
        ) from exc
    return YOLO(str(model))
