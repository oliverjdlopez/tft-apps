"""Verify the round label contract survives removal of annotation tooling."""

import json

import pytest

from round_classifier.config import load_round_labels


def test_default_round_labels(monkeypatch):
    """Keep every original stage/round identifier in its original order."""
    monkeypatch.delenv("VOD_ROUND_LABEL_CONFIG", raising=False)
    assert load_round_labels() == tuple(f"{stage}{round_}" for stage in range(1, 8) for round_ in range(1, 8))


@pytest.mark.parametrize("labels", [[], ["11", "11"], ["../11"], [11], {"labels": ["11"]}])
def test_invalid_custom_round_labels(tmp_path, monkeypatch, labels):
    """Reject configurations that cannot safely identify round results."""
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(labels), encoding="utf-8")
    monkeypatch.setenv("VOD_ROUND_LABEL_CONFIG", str(path))
    with pytest.raises(RuntimeError, match="Round labels"):
        load_round_labels()


def test_custom_round_labels(tmp_path, monkeypatch):
    """Allow an independent custom round label list."""
    path = tmp_path / "labels.json"
    path.write_text('["11", "21"]', encoding="utf-8")
    monkeypatch.setenv("VOD_ROUND_LABEL_CONFIG", str(path))
    assert load_round_labels() == ("11", "21")
