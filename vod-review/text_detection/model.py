"""Ultralytics YOLO model loading for text bounding-box detection."""

from __future__ import annotations

from pathlib import Path
from functools import lru_cache
import time
from typing import Any
from urllib.request import urlretrieve


DEFAULT_MODEL = Path("artifacts/text-detection/train/weights/best.pt")
PRETRAINED_MODEL_URL = (
    "https://huggingface.co/RoyRud1902/yolo11n-text/resolve/main/best.pt"
)


def ensure_pretrained_model(model: str | Path = DEFAULT_MODEL) -> Path:
    """Download the pretrained text detector when the default checkpoint is absent."""
    model_path = Path(model)
    if model_path.exists():
        return model_path
    if model_path != DEFAULT_MODEL:
        raise FileNotFoundError(f"Text-detection checkpoint does not exist: {model_path}")

    model_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = model_path.with_suffix(".download.pt")
    print(f"Downloading pretrained text detector to {model_path}")
    try:
        urlretrieve(PRETRAINED_MODEL_URL, temporary_path)
        temporary_path.replace(model_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return model_path


def load_yolo(model: str | Path = DEFAULT_MODEL) -> Any:
    """Load a YOLO detection checkpoint or pretrained model name."""
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError(
            "ultralytics is required for text detection; run `uv sync` first"
        ) from exc
    return YOLO(str(ensure_pretrained_model(model)))


@lru_cache(maxsize=1)
def get_text_detector() -> Any:
    """Load and reuse the text detector used by round classification."""
    from backend.tracing import trace_event

    started = time.perf_counter()
    detector = load_yolo()
    trace_event(
        "model_initialized",
        component="text_detector",
        model=str(DEFAULT_MODEL),
        initialization_ms=f"{(time.perf_counter() - started) * 1000:.2f}",
    )
    return detector


@lru_cache(maxsize=1)
def inference_device() -> str | int:
    """Return an explicit Ultralytics device, preferring an available CUDA GPU."""
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return 0
    mps = getattr(getattr(torch, 'backends', None), 'mps', None)
    return 'mps' if mps is not None and mps.is_available() else 'cpu'
