from types import SimpleNamespace
import sys

from round_classifier import ocr
from text_detection import model


def test_apple_provider_selection(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    assert ocr.recognition_providers(['CoreMLExecutionProvider', 'CPUExecutionProvider']) == ['CoreMLExecutionProvider', 'CPUExecutionProvider']
    assert ocr.recognition_providers(['CPUExecutionProvider']) == ['CPUExecutionProvider']


def test_mps_detector_selection_and_cpu_fallback(monkeypatch):
    available = [True]
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: available[0]))))
    model.inference_device.cache_clear()
    assert model.inference_device() == 'mps'
    available[0] = False
    model.inference_device.cache_clear()
    assert model.inference_device() == 'cpu'
    model.inference_device.cache_clear()


def test_coreml_options_and_initialization_fallback(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(get_available_providers=lambda: ['CoreMLExecutionProvider', 'CPUExecutionProvider']))
    calls = []
    def build(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            assert kwargs['device'] == 'cpu'
            assert kwargs['engine_config']['provider_options'][0]['MLComputeUnits'] == 'CPUAndGPU'
            raise RuntimeError('Core ML compilation failed')
        return object()
    monkeypatch.setitem(sys.modules, 'paddleocr', SimpleNamespace(TextRecognition=build))
    ocr.get_digit_recognizer.cache_clear()
    try:
        ocr.get_digit_recognizer()
        assert calls[1]['engine_config']['providers'] == ['CPUExecutionProvider']
    finally:
        ocr.get_digit_recognizer.cache_clear()
