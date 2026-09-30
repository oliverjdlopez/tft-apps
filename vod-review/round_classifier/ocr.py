from __future__ import annotations

from functools import lru_cache
import re
import time
import sys
from typing import Any, Iterable

import numpy as np
from PIL import Image

from backend.tracing import detailed_profiling_enabled, trace_event


OCR_MODEL = "en_PP-OCRv5_mobile_rec"
OCR_MIN_CONFIDENCE = 0.70
_runtime_status: dict[str, str] = {}


def runtime_status():
    return dict(_runtime_status)


def recognition_providers(available):
    if 'CUDAExecutionProvider' in available:
        return ['CUDAExecutionProvider', 'CPUExecutionProvider']
    if sys.platform == 'darwin' and 'CoreMLExecutionProvider' in available:
        return ['CoreMLExecutionProvider', 'CPUExecutionProvider']
    return ['CPUExecutionProvider']
SEPARATED_ROUND_TEXT = re.compile(r"(?<!\d)(\d)\s*[-–—.:/]\s*(\d)")
COMPACT_ROUND_TEXT = re.compile(r"\s*(\d)(\d)\s*")


@lru_cache(maxsize=1)
def get_digit_recognizer() -> Any:
    """Load PaddleOCR's small English/numeric recognizer once per process."""
    try:
        from paddleocr import TextRecognition
    except ImportError as exc:
        raise RuntimeError(
            "PaddleOCR is required for OCR-first round classification; run `uv sync`"
        ) from exc
    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError("ONNX Runtime is required for OCR inference") from exc
    providers = ort.get_available_providers()
    selected_providers = recognition_providers(providers)
    started = time.perf_counter()
    def build(selected):
        cuda = selected[0] == 'CUDAExecutionProvider'
        config = {
            'device_type': 'gpu' if cuda else 'cpu',
            'device_id': 0,
            'providers': selected,
        }
        if selected[0] == 'CoreMLExecutionProvider':
            config['provider_options'] = [
                {'ModelFormat': 'MLProgram', 'MLComputeUnits': 'CPUAndGPU'}, {},
            ]
        return TextRecognition(
            model_name=OCR_MODEL,
            engine="onnxruntime",
            device="gpu:0" if cuda else "cpu",
            engine_config=config,
        )
    try:
        recognizer = build(selected_providers)
    except Exception as exc:  # Native ONNX provider errors do not inherit RuntimeError.
        if selected_providers == ['CPUExecutionProvider']:
            raise
        trace_event('ocr_initialization_fallback', error=str(exc))
        recognizer = build(['CPUExecutionProvider'])
    predictor = getattr(recognizer, "paddlex_predictor", None)
    runner = getattr(predictor, "runner", None)
    session = getattr(runner, "session", None)
    actual_providers = session.get_providers() if session is not None else selected_providers
    _runtime_status['recognition'] = ', '.join(actual_providers)
    trace_event(
        "model_initialized",
        component="ocr_recognizer",
        model=OCR_MODEL,
        initialization_ms=f"{(time.perf_counter() - started) * 1000:.2f}",
        requested_providers=",".join(selected_providers),
        actual_providers=",".join(actual_providers),
    )
    return recognizer


def recognize_images(images, recognizer=None):
    """Recognize whole RGB crops with the configured provider and CPU fallback."""
    if not images:
        return []
    recognizer = recognizer or get_digit_recognizer()
    predictor = getattr(recognizer, 'paddlex_predictor', None)
    from round_classifier.profiling import instrument_recognizer
    instrument_recognizer(recognizer)
    try:
        results = list(recognizer.predict(input=images, batch_size=len(images)))
    except Exception as exc:
        session = getattr(getattr(predictor, 'runner', None), 'session', None)
        if session is None or session.get_providers() == ['CPUExecutionProvider']:
            raise
        trace_event('ocr_runtime_cpu_fallback', error=str(exc))
        session.set_providers(['CPUExecutionProvider'])
        results = list(recognizer.predict(input=images, batch_size=len(images)))
    session = getattr(getattr(predictor, 'runner', None), 'session', None)
    if session is not None:
        _runtime_status['recognition'] = ', '.join(session.get_providers())
    if len(results) != len(images):
        raise RuntimeError('OCR returned a different number of results than input crops')
    return results


def normalize_round_text(text: str, class_names: Iterable[str]) -> str | None:
    """Normalize OCR text such as '3-2' to a configured classifier label such as '32'."""
    match = SEPARATED_ROUND_TEXT.search(text)
    if match is None:
        match = COMPACT_ROUND_TEXT.fullmatch(text)
    if match is None:
        return None
    label = "".join(match.groups())
    return label if label in set(class_names) else None


def _copy_detection_rows_to_host(rows: list[Any]) -> np.ndarray:
    """Stack selected detector rows and perform one host transfer for the batch."""
    if not rows:
        return np.empty((0, 5), dtype=np.float32)
    if isinstance(rows[0], np.ndarray):
        return np.stack(rows)
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for text detection") from exc
    stacked = torch.stack(rows).detach()
    started = time.perf_counter()
    cuda_ms = None
    if stacked.device.type == "cuda" and torch.cuda.is_available():
        start_event = torch.cuda.Event(enable_timing=True)
        end_event = torch.cuda.Event(enable_timing=True)
        start_event.record()
        host = stacked.cpu()
        end_event.record()
        end_event.synchronize()
        cuda_ms = start_event.elapsed_time(end_event)
    else:
        host = stacked.cpu()
    trace_event(
        "detector_transfer_stage",
        direction="d2h",
        rows=len(rows),
        bytes=stacked.numel() * stacked.element_size(),
        wall_ms=f"{(time.perf_counter() - started) * 1000:.4f}",
        cuda_ms=f"{cuda_ms:.4f}" if cuda_ms is not None else None,
    )
    return host.numpy()


def detect_and_recognize_round_images(
    images: list[Image.Image],
    class_names: Iterable[str],
    minimum_confidence: float = OCR_MIN_CONFIDENCE,
    detector: Any | None = None,
    recognizer: Any | None = None,
) -> list[dict[str, Any]]:
    """Detect text regions, OCR each box, and select the best valid round token."""
    if not images:
        return []
    from text_detection.model import get_text_detector, inference_device

    detector = detector or get_text_detector()
    recognizer = recognizer or get_digit_recognizer()

    from text_detection.profiling import instrument_yolo_predictor, yolo_stage_metrics

    cold_detector_batch = getattr(detector, "predictor", None) is None
    if detailed_profiling_enabled():
        instrument_yolo_predictor(detector)
    detection_started = time.perf_counter()
    selected_device = getattr(detector, '_vod_fallback_device', inference_device())
    try:
        detection_results = detector.predict(
        source=images,
        verbose=False,
        device=selected_device,
        )
    except (RuntimeError, NotImplementedError) as exc:
        if selected_device == 'cpu':
            raise
        trace_event('text_detection_cpu_fallback', error=str(exc))
        detector.to('cpu')
        detector.predictor = None
        detector._vod_fallback_device = 'cpu'
        detection_results = detector.predict(source=images, verbose=False, device='cpu')
    _runtime_status['text_detection'] = str(getattr(getattr(detector, 'predictor', None), 'device', selected_device))
    detection_ms = (time.perf_counter() - detection_started) * 1000
    trace_event(
        "text_detection_batch",
        inputs=len(images),
        requested_device=inference_device(),
        detection_ms=f"{detection_ms:.2f}",
        cold_batch=cold_detector_batch,
    )
    predictor = getattr(detector, "predictor", None)
    actual_device = getattr(predictor, "device", None)
    trace_event(
        "text_detection_stage_profile",
        inputs=len(images),
        actual_device=str(actual_device),
        detailed=detailed_profiling_enabled(),
        **yolo_stage_metrics(detector, detection_results),
    )
    if cold_detector_batch:
        trace_event(
            "model_first_batch",
            component="text_detector",
            first_batch_ms=f"{detection_ms:.2f}",
            includes_preprocess_and_inference=True,
        )
    if detailed_profiling_enabled():
        instrument_yolo_predictor(detector)
    if len(detection_results) != len(images):
        raise RuntimeError("Text detector returned a different number of results than inputs")

    candidates_by_image: list[list[dict[str, Any]]] = [[] for _ in images]
    ocr_inputs: list[np.ndarray] = []
    candidate_order: list[dict[str, Any]] = []
    detected_image_indices: list[int] = []
    selected_rows: list[Any] = []
    for image_index, result in enumerate(detection_results):
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            continue
        best_row = boxes.data[boxes.conf.argmax()]
        selected_rows.append(best_row[[0, 1, 2, 3, -2]])
        detected_image_indices.append(image_index)

    extraction_started = time.perf_counter()
    host_rows = _copy_detection_rows_to_host(selected_rows)
    trace_event(
        "text_detection_extract_batch",
        detected_images=len(detected_image_indices),
        transferred_rows=len(host_rows),
        transfers=int(bool(selected_rows)),
        extraction_ms=f"{(time.perf_counter() - extraction_started) * 1000:.2f}",
    )
    for image_index, row in zip(detected_image_indices, host_rows, strict=True):
        image = images[image_index]
        left = max(0, int(row[0]))
        top = max(0, int(row[1]))
        right = min(image.width, int(row[2] + 0.9999))
        bottom = min(image.height, int(row[3] + 0.9999))
        if right <= left or bottom <= top:
            continue
        candidate = {
            "bbox": [left, top, right, bottom],
            "detection_confidence": float(row[4]),
        }
        candidates_by_image[image_index].append(candidate)
        candidate_order.append(candidate)
        ocr_inputs.append(np.asarray(image.crop((left, top, right, bottom)).convert("RGB")))

    if ocr_inputs:
        from round_classifier.profiling import instrument_recognizer, recognizer_stage_metrics

        predictor = getattr(recognizer, "paddlex_predictor", None)
        cold_ocr_batch = not getattr(predictor, "_vod_seen_batch", False)
        instrument_recognizer(recognizer)
        recognition_started = time.perf_counter()
        ocr_results = recognize_images(ocr_inputs, recognizer)
        recognition_ms = (time.perf_counter() - recognition_started) * 1000
        if predictor is not None:
            predictor._vod_seen_batch = True
        trace_event(
            "ocr_recognition_batch",
            inputs=len(ocr_inputs),
            recognition_ms=f"{recognition_ms:.2f}",
            cold_batch=cold_ocr_batch,
        )
        trace_event(
            "ocr_stage_profile",
            inputs=len(ocr_inputs),
            detailed=detailed_profiling_enabled(),
            **recognizer_stage_metrics(recognizer),
        )
        if cold_ocr_batch:
            trace_event(
                "model_first_batch",
                component="ocr_recognizer",
                first_batch_ms=f"{recognition_ms:.2f}",
                includes_preprocess_and_inference=True,
            )
        if len(ocr_results) != len(ocr_inputs):
            raise RuntimeError("PaddleOCR returned a different number of results than boxes")
        configured_classes = tuple(class_names)
        for candidate, result in zip(candidate_order, ocr_results, strict=True):
            payload = result.json.get("res", result.json)
            raw_text = str(payload.get("rec_text", ""))
            ocr_confidence = float(payload.get("rec_score", 0.0))
            parsed_label = normalize_round_text(raw_text, configured_classes)
            candidate.update(
                raw_ocr_text=raw_text,
                ocr_confidence=ocr_confidence,
                parsed_label=parsed_label,
                has_round_separator=SEPARATED_ROUND_TEXT.search(raw_text) is not None,
                accepted=parsed_label is not None and ocr_confidence >= minimum_confidence,
            )

    outputs = []
    for candidates in candidates_by_image:
        selected = candidates[0] if candidates and candidates[0].get("accepted") else None
        outputs.append({"prediction": selected, "candidates": candidates})
    return outputs
