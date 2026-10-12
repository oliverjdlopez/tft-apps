"""Keep the portable decision-workflow evaluation coherent and evidence bounded."""
from __future__ import annotations

import json
from pathlib import Path

from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle
from evals.langfuse.utils import validate_case_semantics
from evals.langfuse.assistant_workspace import current_execution
from evals.assistant_execution import require_bundle_captures


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "evals/datasets/decision_workflows.json"
BUNDLE = json.loads(SOURCE.read_text(encoding="utf-8"))


def test_portable_suite_validates_and_covers_player_decision_workflows() -> None:
    """Validate schema-v3 inputs and guard the intended workflow coverage."""
    bundle = validate_bundle(BUNDLE)
    validate_case_semantics(bundle["suite"], bundle["items"])

    assert bundle["schema_version"] == 3
    assert bundle["dataset_name"] == "decision-workflows"
    assert bundle["suite"]["assistant"] == "chat"
    assert bundle["suite"]["execution"] == "live"
    assert len(bundle["items"]) == 8
    assert len({item["id"] for item in bundle["items"]}) == 8
    assert {item["metadata"]["case"] for item in bundle["items"]} == {
        "quick_frequency_lookup",
        "fixed_shell_third_slot",
        "artifact_shell_dependence",
        "unbounded_comp_shell_discovery",
        "audit_surprising_result",
        "suppressed_comparison",
        "no_clear_difference",
        "roll_or_level_evidence_ceiling",
    }

    snapshots = ROOT / "evals/langfuse/snapshots"
    entry = next(item for item in load_catalog(snapshots) if item["name"] == "decision_workflows")
    frozen = load_snapshot(entry["snapshot"], snapshots)
    assert frozen["dataset_name"] == "decision-workflows"
    assert frozen["suite"]["managed_workflow"] is True
    frozen_items = {item["id"]: item for item in frozen["items"]}
    assert set(frozen_items) == {item["id"] for item in bundle["items"]}
    for item in bundle["items"]:
        assert frozen_items[item["id"]]["input"] == item["input"]
        assert frozen_items[item["id"]]["expected_output"] == item["expected_output"]


def test_cases_use_native_quality_rubrics_without_unverified_gold_or_forced_tools() -> None:
    """Keep evaluation criteria semantic and avoid pretending data gold is known."""
    for item in BUNDLE["items"]:
        metadata = item["metadata"]
        assert metadata["evidence_status"] == "gold_unverified"
        assert metadata["quality_profile"] == "answer_quality"
        assert item["expected_output"]["requirements"]
        assert metadata.get("deterministic_checks", []) == []
        assert "reference" not in item["expected_output"]

    assert "no fixed tool sequence" in BUNDLE["provenance"]["scoring"].lower()
    assert "no item ranking" in BUNDLE["provenance"]["evidence"]


def test_fresh_local_capture_makes_seed_valid_for_captured_live_runs() -> None:
    """Prepare a captured, explicitly targeted bundle without external calls."""
    bundle = validate_bundle(BUNDLE)
    execution = current_execution(bundle["suite"], bundle["config"]["variants"])
    suite = {**bundle["suite"], "database": "eval_test"}
    captured_bundle = {**bundle, "suite": suite, "execution": execution}

    validated = validate_bundle(captured_bundle)
    require_bundle_captures(validated)

    assert set(execution["graphs"]) == {"baseline"}
    assert len(validated["items"]) == 8
    assert validated["suite"]["database"] == "eval_test"
