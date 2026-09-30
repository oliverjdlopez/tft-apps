from __future__ import annotations

from functools import lru_cache
from typing import Any


class OCRRoundClassifierPredictor:
    """Recognize configured round labels with YOLO text detection and PaddleOCR."""

    device_label = "ocr"
    evaluation_minimum_confidence = 0.50

    def __init__(self, class_names: tuple[str, ...]) -> None:
        if not class_names:
            raise ValueError("OCR round classification requires configured class names")
        self.class_names = class_names

    def predict_batch(self, crops: list[Any]) -> list[tuple[str, float]]:
        from PIL import Image
        from round_classifier.ocr import detect_and_recognize_round_images

        detections = detect_and_recognize_round_images(
            [Image.fromarray(crop) for crop in crops],
            self.class_names,
            minimum_confidence=self.evaluation_minimum_confidence,
        )
        return [
            (prediction["parsed_label"], prediction["ocr_confidence"])
            if (prediction := detection["prediction"]) is not None
            else ("unknown", 0.0)
            for detection in detections
        ]


@lru_cache(maxsize=1)
def get_ocr_classifier(class_names: tuple[str, ...]) -> OCRRoundClassifierPredictor:
    return OCRRoundClassifierPredictor(class_names)
