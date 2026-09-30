import sys
from types import SimpleNamespace

import pytest

from unit_segmentation.model import load_yolo


def test_load_yolo_constructs_ultralytics_model(monkeypatch):
    calls = []
    monkeypatch.setitem(
        sys.modules,
        "ultralytics",
        SimpleNamespace(YOLO=lambda model: calls.append(model) or object()),
    )

    loaded = load_yolo("custom.pt")

    assert loaded is not None
    assert calls == ["custom.pt"]


def test_load_yolo_reports_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, "ultralytics", None)

    with pytest.raises(RuntimeError, match="ultralytics is required"):
        load_yolo()
