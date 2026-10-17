"""Calibrate scoring mechanics against deliberately right and wrong judgments."""

from copy import deepcopy
import json
import subprocess
import sys

import pytest

from evals.calibration import calibrate, judge_request, load_corpus


def labelled_grades(corpus):
    """Provide oracle labels only for calibration-mechanics unit tests."""
    return {"evaluator": {"name": "fixture-only", "version": "1"}, "grades": [
        {"case": case["id"], "candidate": candidate["id"], "criterion": criterion,
         "score": float(label), "reason": "Synthetic fixture judgment."}
        for case in corpus["cases"] for candidate in case["candidates"]
        for criterion, label in candidate["expected"].items()]}


def test_confusion_counts_detect_both_kinds_of_judge_error():
    """Hand-count one false positive and one false negative independently."""
    corpus = load_corpus()
    grades = labelled_grades(corpus)
    positive = next(row for row in grades["grades"] if row["score"] == 1)
    negative = next(row for row in grades["grades"] if row["score"] == 0)
    positive["score"], negative["score"] = 0.2, 0.95
    report = calibrate(corpus, grades)
    assert report["confusion"]["false_positive"] == 1
    assert report["confusion"]["false_negative"] == 1
    assert len(report["disagreements"]) == 2
    assert report["agreement"] == pytest.approx(1 - 2 / len(grades["grades"]))
    assert report["review"]["status"] == "proposed"


@pytest.mark.parametrize("damage", ["missing", "duplicate", "nan", "unknown", "version"])
def test_incomplete_or_ambiguous_grades_cannot_be_calibrated(damage):
    """Missing grades, nonfinite results and unidentified evaluators cannot pass."""
    corpus = load_corpus()
    grades = labelled_grades(corpus)
    if damage == "missing":
        grades["grades"].pop()
    elif damage == "duplicate":
        grades["grades"].append(deepcopy(grades["grades"][0]))
    elif damage == "nan":
        grades["grades"][0]["score"] = float("nan")
    elif damage == "unknown":
        grades["grades"][0]["candidate"] = "absent"
    else:
        grades["evaluator"].pop("version")
    with pytest.raises(ValueError):
        calibrate(corpus, grades)


def test_unreviewed_labels_cannot_be_promoted_and_never_reach_judge():
    """Keep proposed human judgments explicit and prevent answer-key leakage."""
    with pytest.raises(ValueError, match="human review"):
        load_corpus(require_reviewed=True)
    request = judge_request(load_corpus())
    assert all("expected" not in candidate for case in request["cases"] for candidate in case["candidates"])


def test_mock_judge_adapter_uses_real_cli_protocol_without_paid_calls():
    """Exercise external grading protocol with a local process and frozen identity."""
    corpus = load_corpus()
    grades = labelled_grades(corpus)
    code = "import json,sys; request=json.load(sys.stdin); assert 'expected' not in str(request); print(" + repr(json.dumps(grades)) + ")"
    result = subprocess.run([sys.executable, "-m", "evals.calibration", "--allow-paid", "--judge-command", sys.executable, "-c", code],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["agreement"] == 1
