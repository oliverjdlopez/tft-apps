"""Runtime text bounding-box detector used by round OCR."""

from .model import DEFAULT_MODEL, load_yolo

__all__ = ["DEFAULT_MODEL", "load_yolo"]
