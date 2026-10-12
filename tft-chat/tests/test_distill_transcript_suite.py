"""Validate portable source-fidelity cases and captured distiller execution offline."""

import json
from pathlib import Path

from evals.assistant_execution import require_bundle_captures
from evals.langfuse.assistant_workspace import current_execution
from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle
from evals.langfuse.utils import validate_case_semantics


ROOT = Path(__file__).resolve().parents[1]


def test_distillation_suite_matches_catalog_and_captures_only_the_distiller() -> None:
    """Keep synthetic source cases usable through the real captured evaluation path."""
    bundle = validate_bundle(json.loads(
        (ROOT / "evals/datasets/distill-transcript.json").read_text(encoding="utf-8"),
    ))
    validate_case_semantics(bundle["suite"], bundle["items"])
    snapshots = ROOT / "evals/langfuse/snapshots"
    entry = next(row for row in load_catalog(snapshots) if row["name"] == "distill-transcript")
    assert load_snapshot(entry["snapshot"], snapshots) == bundle
    assert {item["metadata"]["case"] for item in bundle["items"]} == {
        "conditional_rationale", "explicit_correction_jsonl",
        "disagreement_and_missing_visuals", "article_dates_and_reported_statistics",
        "embedded_instruction_boundary", "irrelevant_source",
    }
    execution = current_execution(bundle["suite"], bundle["config"]["variants"])
    captured = validate_bundle({**bundle, "execution": execution})
    require_bundle_captures(captured)
    graph = execution["graphs"]["baseline"]
    spec = graph["specs"]["distill-transcript"]
    assert spec["handoff_names"] == []
    assert spec["repository_context"] is False
    assert spec["skill_names"] == []
