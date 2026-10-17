"""Compare versioned semantic judge grades with proposed or reviewed labels.

No model calls occur by default. --judge-command is an explicit opt-in adapter:
it reads one JSON request from stdin and writes a complete grades document to
stdout. Requests never include expected labels. Existing native judge exports
can instead be normalized to the same document and passed with --grades.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

CORPUS = Path(__file__).resolve().parent / "datasets/semantic-calibration.json"


def load_corpus(path=CORPUS, require_reviewed=False):
    """Validate criterion-level labels without claiming proposed labels are reviewed."""
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    if corpus.get("schema_version") != 1 or not corpus.get("cases"):
        raise ValueError("Invalid semantic calibration corpus")
    review = corpus.get("review", {})
    if require_reviewed and (review.get("status") != "reviewed" or not review.get("reviewer")):
        raise ValueError("Semantic labels require explicit human review")
    identities = set()
    for case in corpus["cases"]:
        criteria = [row["id"] for row in case["criteria"]]
        if len(criteria) != len(set(criteria)) or not criteria or not case.get("source"):
            raise ValueError(f"Invalid calibration criteria: {case['id']}")
        for candidate in case["candidates"]:
            identity = case["id"] + "/" + candidate["id"]
            if identity in identities or set(candidate["expected"]) != set(criteria):
                raise ValueError(f"Duplicate or incomplete candidate: {identity}")
            if not candidate.get("output") or any(type(value) is not bool for value in candidate["expected"].values()):
                raise ValueError(f"Invalid criterion labels: {identity}")
            identities.add(identity)
    return corpus


def judge_request(corpus):
    """Construct a source/response/criteria request without leaking expected labels."""
    return {"schema_version": 1, "cases": [
        {"id": case["id"], "kind": case["kind"], "source": case["source"], "criteria": case["criteria"],
         "candidates": [{"id": candidate["id"], "output": candidate["output"]} for candidate in case["candidates"]]}
        for case in corpus["cases"]]}


def calibrate(corpus, grades, threshold=0.8):
    """Reject incomplete grading and measure false positives/negatives by criterion."""
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Calibration threshold must be finite and within 0..1")
    evaluator = grades.get("evaluator", {})
    if not evaluator.get("name") or not evaluator.get("version"):
        raise ValueError("Grades require a frozen evaluator name and version")
    expected = {(case["id"], candidate["id"], criterion): (label, case["kind"])
                for case in corpus["cases"] for candidate in case["candidates"]
                for criterion, label in candidate["expected"].items()}
    supplied = {}
    for row in grades["grades"]:
        key = (row["case"], row["candidate"], row["criterion"])
        score = row["score"]
        if key in supplied or key not in expected:
            raise ValueError(f"Duplicate or unknown semantic grade: {key}")
        if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1 or not row.get("reason"):
            raise ValueError(f"Invalid semantic grade: {key}")
        supplied[key] = row
    if expected.keys() != supplied.keys():
        raise ValueError(f"Missing semantic grades: {sorted(expected.keys() - supplied.keys())}")
    totals = dict(true_positive=0, true_negative=0, false_positive=0, false_negative=0)
    by_kind, disagreements = {}, []
    for key, (label, kind) in expected.items():
        positive = supplied[key]["score"] >= threshold
        category = ("true_" if positive == label else "false_") + ("positive" if positive else "negative")
        totals[category] += 1
        by_kind.setdefault(kind, dict.fromkeys(totals, 0))[category] += 1
        if positive != label:
            disagreements.append({"case": key[0], "candidate": key[1], "criterion": key[2],
                                  "expected": label, "score": supplied[key]["score"], "reason": supplied[key]["reason"]})
    fingerprint = hashlib.sha256(json.dumps(corpus, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"schema_version": 1, "corpus_sha256": fingerprint, "review": corpus["review"],
            "evaluator": evaluator, "threshold": threshold, "criteria": len(expected),
            "confusion": totals, "by_kind": by_kind, "disagreements": disagreements,
            "agreement": (len(expected) - len(disagreements)) / len(expected)}


def main():
    """Report calibration; external judge adapters require an explicit paid opt-in."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS)
    parser.add_argument("--grades", type=Path)
    parser.add_argument("--require-reviewed", action="store_true")
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--judge-command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    corpus = load_corpus(args.corpus, args.require_reviewed)
    if args.judge_command:
        if not args.allow_paid or args.grades:
            parser.error("Judge commands require --allow-paid and cannot be combined with --grades")
        result = subprocess.run(args.judge_command, input=json.dumps(judge_request(corpus)), text=True,
                                capture_output=True, check=True, timeout=600)
        grades = json.loads(result.stdout)
    elif args.grades:
        grades = json.loads(args.grades.read_text(encoding="utf-8"))
    else:
        print(json.dumps({"status": "awaiting_grades", "review": corpus["review"],
                          "cases": len(corpus["cases"]), "candidates": sum(len(case["candidates"]) for case in corpus["cases"])}))
        return 0
    print(json.dumps(calibrate(corpus, grades), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
