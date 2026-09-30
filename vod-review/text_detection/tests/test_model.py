import sys
from types import SimpleNamespace

import pytest

from text_detection import model
from text_detection.model import get_text_detector, load_yolo


def test_load_yolo_constructs_ultralytics_model(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "ultralytics",
        SimpleNamespace(YOLO=lambda model: calls.append(model) or object()),
    )

    monkeypatch.setattr(model, "ensure_pretrained_model", lambda path: path)
    assert load_yolo("text.pt") is not None
    assert calls == ["text.pt"]


def test_load_yolo_reports_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", None)

    with pytest.raises(RuntimeError, match="ultralytics is required for text detection"):
        load_yolo()


def test_text_detector_is_loaded_once(monkeypatch):
    calls = []
    model.get_text_detector.cache_clear()
    monkeypatch.setattr(model, "load_yolo", lambda: calls.append(True) or object())

    assert get_text_detector() is get_text_detector()
    assert calls == [True]
    model.get_text_detector.cache_clear()


def test_inference_device_prefers_available_cuda(monkeypatch):
    model.inference_device.cache_clear()
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )

    assert model.inference_device() == 0
    model.inference_device.cache_clear()


def test_default_model_downloads_from_hugging_face(monkeypatch, tmp_path):
    destination = tmp_path / "weights" / "best.pt"
    monkeypatch.setattr(model, "DEFAULT_MODEL", destination)

    def fake_download(url, output):
        assert url == model.PRETRAINED_MODEL_URL
        output.write_bytes(b"checkpoint")

    monkeypatch.setattr(model, "urlretrieve", fake_download)

    assert model.ensure_pretrained_model(destination) == destination
    assert destination.read_bytes() == b"checkpoint"
