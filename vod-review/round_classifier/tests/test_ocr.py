import sys
from types import SimpleNamespace

import numpy as np
from PIL import Image
import torch

from backend.tracing import capture_trace_events, trace_context
from round_classifier import ocr
from round_classifier.ocr import detect_and_recognize_round_images, normalize_round_text


class FakeRecognizer:
    def __init__(self, outputs):
        self.outputs = outputs

    def predict(self, **options):
        assert options["batch_size"] == len(options["input"])
        return [SimpleNamespace(json={"res": output}) for output in self.outputs]


def boxes(confidences, coordinates):
    class Boxes:
        data = torch.tensor(
            [coordinates[index] + [confidence, 0.0] for index, confidence in enumerate(confidences)],
            dtype=torch.float64,
        ).reshape((-1, 6))
        conf = data[:, -2]
        xyxy = data[:, :4]

        def __len__(self):
            return len(confidences)

    return Boxes()


def test_normalize_round_text_accepts_separator_and_configured_class():
    assert normalize_round_text(" 3-2 ", ["31", "32"]) == "32"
    assert normalize_round_text("5-1 021", ["51"]) == "51"
    assert normalize_round_text("1-109", ["11"]) == "11"
    assert normalize_round_text("32", ["31", "32"]) == "32"
    assert normalize_round_text("3Z", ["32"]) is None
    assert normalize_round_text("38", ["32"]) is None


def test_detection_sends_only_each_image_highest_confidence_box_to_ocr(monkeypatch):
    detector = SimpleNamespace(
        predict=lambda **_options: [SimpleNamespace(boxes=boxes(
            [0.4, 0.9], [[0, 0, 10, 10], [10, 5, 70, 25]]
        ))]
    )
    recognizer = FakeRecognizer([{"rec_text": "3-2", "rec_score": 0.95}])
    transfers = []
    original_transfer = ocr._copy_detection_rows_to_host
    monkeypatch.setattr(
        ocr,
        "_copy_detection_rows_to_host",
        lambda rows: transfers.append(len(rows)) or original_transfer(rows),
    )
    monkeypatch.setattr("text_detection.model.inference_device", lambda: "cpu")

    result = detect_and_recognize_round_images(
        [Image.new("RGB", (100, 40))], ["32"], detector=detector, recognizer=recognizer
    )

    assert result == [{
        "prediction": result[0]["candidates"][0],
        "candidates": [{
            "bbox": [10, 5, 70, 25], "detection_confidence": 0.9,
            "raw_ocr_text": "3-2", "ocr_confidence": 0.95, "parsed_label": "32",
            "has_round_separator": True, "accepted": True,
        }],
    }]
    assert transfers == [1]


def test_detection_transfers_mixed_batch_once_and_preserves_image_order(monkeypatch):
    detector = SimpleNamespace(
        predict=lambda **_options: [
            SimpleNamespace(boxes=boxes([0.8], [[5, 4, 35, 20]])),
            SimpleNamespace(boxes=boxes([], [])),
            SimpleNamespace(boxes=boxes([0.4, 0.9], [[0, 0, 10, 10], [20, 6, 75, 30]])),
        ]
    )
    recognizer = FakeRecognizer([
        {"rec_text": "3-1", "rec_score": 0.91},
        {"rec_text": "3-2", "rec_score": 0.92},
    ])
    transfers = []
    original_transfer = ocr._copy_detection_rows_to_host
    monkeypatch.setattr(
        ocr,
        "_copy_detection_rows_to_host",
        lambda rows: transfers.append(len(rows)) or original_transfer(rows),
    )
    monkeypatch.setattr("text_detection.model.inference_device", lambda: "cpu")

    with trace_context(
        job_id="job-1", batch_index=4, batch_capacity=64, actual_batch_size=3
    ), capture_trace_events() as events:
        results = detect_and_recognize_round_images(
            [Image.new("RGB", (100, 40)) for _ in range(3)],
            ["31", "32"],
            detector=detector,
            recognizer=recognizer,
        )

    assert transfers == [2]
    assert [result["prediction"]["parsed_label"] if result["prediction"] else None for result in results] == [
        "31", None, "32",
    ]
    assert results[0]["prediction"]["bbox"] == [5, 4, 35, 20]
    assert results[2]["prediction"]["bbox"] == [20, 6, 75, 30]
    transfer = next(event for event in events if event["event"] == "detector_transfer_stage")
    assert transfer["rows"] == 2
    assert transfer["direction"] == "d2h"
    assert transfer["batch_index"] == 4
    extraction = next(
        event for event in events if event["event"] == "text_detection_extract_batch"
    )
    assert extraction["transfers"] == 1
    assert extraction["detected_images"] == 2


def test_detection_returns_no_prediction_when_yolo_finds_no_box(monkeypatch):
    detector = SimpleNamespace(
        predict=lambda **_options: [SimpleNamespace(boxes=boxes([], []))]
    )
    monkeypatch.setattr("text_detection.model.inference_device", lambda: "cpu")
    transfers = []
    monkeypatch.setattr(
        ocr,
        "_copy_detection_rows_to_host",
        lambda rows: transfers.append(len(rows)) or np.empty((0, 5)),
    )

    assert detect_and_recognize_round_images(
        [Image.new("RGB", (100, 40))], ["32"], detector=detector, recognizer=FakeRecognizer([])
    ) == [{"prediction": None, "candidates": []}]
    assert transfers == [0]


def test_digit_recognizer_prefers_cuda_onnx_provider(monkeypatch):
    calls = []
    ocr.get_digit_recognizer.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "paddleocr",
        SimpleNamespace(TextRecognition=lambda **options: calls.append(options) or object()),
    )
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(
            get_available_providers=lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"]
        ),
    )

    ocr.get_digit_recognizer()

    assert calls[0]["device"] == "gpu:0"
    assert calls[0]["engine_config"]["providers"] == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    ocr.get_digit_recognizer.cache_clear()
