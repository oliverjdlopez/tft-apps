from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np

SUPPORTED_SUFFIXES = {".bmp", ".jpeg", ".jpg", ".png", ".webp"}


@dataclass(frozen=True, slots=True)
class Detection:
    label: str
    confidence: float
    x: int
    y: int
    width: int
    height: int
    template: str

    def to_dict(self) -> dict[str, str | float | int]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _Template:
    label: str
    path: Path
    image: np.ndarray


class TemplateMatcher:
    """Locate labeled reference images using normalized template correlation."""

    def __init__(
        self,
        template_dir: Path,
        *,
        threshold: float = 0.85,
        scales: Iterable[float] = (1.0,),
        nms_iou_threshold: float = 0.3,
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be between 0 and 1")
        if not 0.0 <= nms_iou_threshold <= 1.0:
            raise ValueError("nms_iou_threshold must be between 0 and 1")
        self.template_dir = Path(template_dir)
        self.threshold = threshold
        self.scales = tuple(float(scale) for scale in scales)
        if not self.scales or any(scale <= 0 for scale in self.scales):
            raise ValueError("scales must contain positive values")
        self.nms_iou_threshold = nms_iou_threshold
        self.templates = self._load_templates()

    def _load_templates(self) -> tuple[_Template, ...]:
        if not self.template_dir.is_dir():
            raise ValueError(f"Template directory does not exist: {self.template_dir}")
        loaded: list[_Template] = []
        for label_dir in sorted(path for path in self.template_dir.iterdir() if path.is_dir()):
            for path in sorted(label_dir.iterdir()):
                if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                    continue
                image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
                if image is None:
                    raise ValueError(f"Could not read template image: {path}")
                loaded.append(_Template(label_dir.name, path, image))
        if not loaded:
            raise ValueError(
                f"No template images found below {self.template_dir}; "
                "expected templates/<label>/<image>"
            )
        return tuple(loaded)

    def detect(self, image: np.ndarray) -> list[Detection]:
        gray = _to_grayscale(image)
        candidates: list[Detection] = []
        image_height, image_width = gray.shape

        for template in self.templates:
            for scale in self.scales:
                width = max(1, round(template.image.shape[1] * scale))
                height = max(1, round(template.image.shape[0] * scale))
                if width > image_width or height > image_height:
                    continue
                resized = cv2.resize(
                    template.image,
                    (width, height),
                    interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR,
                )
                scores = cv2.matchTemplate(gray, resized, cv2.TM_CCOEFF_NORMED)
                ys, xs = np.where(scores >= self.threshold)
                candidates.extend(
                    Detection(
                        label=template.label,
                        confidence=float(scores[y, x]),
                        x=int(x),
                        y=int(y),
                        width=width,
                        height=height,
                        template=str(template.path),
                    )
                    for y, x in zip(ys, xs, strict=True)
                )

        return _non_maximum_suppression(candidates, self.nms_iou_threshold)


def _to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    if image.ndim == 3 and image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_RGBA2GRAY)
    raise ValueError(f"Expected an HxW, HxWx3, or HxWx4 image, got shape {image.shape}")


def _iou(left: Detection, right: Detection) -> float:
    intersection_width = max(0, min(left.x + left.width, right.x + right.width) - max(left.x, right.x))
    intersection_height = max(0, min(left.y + left.height, right.y + right.height) - max(left.y, right.y))
    intersection = intersection_width * intersection_height
    if intersection == 0:
        return 0.0
    union = left.width * left.height + right.width * right.height - intersection
    return intersection / union


def _non_maximum_suppression(
    detections: Iterable[Detection], iou_threshold: float
) -> list[Detection]:
    kept: list[Detection] = []
    for candidate in sorted(detections, key=lambda detection: detection.confidence, reverse=True):
        if all(_iou(candidate, existing) <= iou_threshold for existing in kept):
            kept.append(candidate)
    return kept
