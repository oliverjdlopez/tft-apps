"""Validate review-case portability and lineage without running an assistant."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.langfuse.content import load_snapshot, validate_bundle
from evals.langfuse.contracts import dataset_schemas
from evals.langfuse.dataset_registration import register_dataset
from evals.langfuse.utils import validate_case_semantics


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "evals" / "datasets" / "unit_expert_review.json"
SOURCE_SNAPSHOT = "8c64292d00a60b99e684b0f44d2e9560ecdb9f41c9b5477df5c897180dabb10b"
CASE_PAGES = {
    "UN4-1-C02": [11, 12],
    "UN4-2-C01": [30, 31],
    "UN4-2-C03": [54, 55],
    "UN4-2-C04": [69, 70],
    "UN4-3-C01": [81, 82],
    "UN4-3-C04": [109, 110],
}


@pytest.fixture
def review_bundle() -> dict:
    """Load the portable seed without registering or exporting a snapshot.

    Returns:
        The repository-authored unit expert review manifest.
    """
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_review_bundle_validates_without_execution(review_bundle: dict) -> None:
    """Validate current schema and registry contracts, not model answer quality."""
    validated = validate_bundle(review_bundle)
    validate_case_semantics(validated["suite"], validated["items"])

    assert validated["schema_version"] == 3
    assert validated["suite"]["assistant"] == "unit_expert"
    assert validated["schemas"] == dataset_schemas(validated["suite"], version=3)
    assert {item["metadata"]["case"] for item in validated["items"]} == set(CASE_PAGES)
    assert validated["prompts"] == {}
    for item in validated["items"]:
        assert item["metadata"]["quality_profile"] == "answer_quality"
        assert item["expected_output"]["requirements"]
        assert item["metadata"]["numeric_ground_truth_verified"] is False
        # These cases need qualitative review of returned evidence. Structural
        # tests must not silently turn that into regexes or mandatory tool calls.
        assert not item["metadata"].get("deterministic_checks")


@pytest.mark.parametrize("case", CASE_PAGES)
def test_review_preserves_original_question_and_lineage(
    review_bundle: dict, case: str,
) -> None:
    """Protect original player inputs and independently traceable review sources.

    Args:
        review_bundle: The unregistered manifest under test.
        case: An original case slug retained by this focused selection.
    """
    source = load_snapshot(SOURCE_SNAPSHOT, ROOT / "evals" / "langfuse" / "snapshots")
    original = next(item for item in source["items"] if item["metadata"]["case"] == case)
    reviewed = next(item for item in review_bundle["items"] if item["metadata"]["case"] == case)

    assert reviewed["input"] == original["input"]
    assert reviewed["id"] == reviewed["metadata"]["case_id"] == f"unit_expert_review/{case}"
    assert reviewed["metadata"]["suite"] == "unit_expert_review"
    for key in (
        "source_case_id", "source_suite_case_id", "source_case_file",
        "source_dataset", "source_dataset_id", "source_item_id", "proposal_lineage",
    ):
        assert reviewed["metadata"][key] == original["metadata"][key]

    evidence = reviewed["metadata"]["review_source"]
    assert evidence["input_snapshot"] == f"evals/langfuse/snapshots/{SOURCE_SNAPSHOT}.json"
    assert evidence["input_case_id"] == original["id"]
    assert evidence["run_id"] == "adea170a7b476b85"
    assert evidence["pages"] == CASE_PAGES[case]
    assert evidence["general_comment_pages"] == [1]
    assert (ROOT / evidence["pdf"]).is_file()


def test_review_import_preserves_cases_in_an_isolated_catalog(
    review_bundle: dict, tmp_path: Path,
) -> None:
    """Exercise the existing registration path without touching live definitions.

    Args:
        review_bundle: The manifest supplied to the regular dataset importer.
        tmp_path: Disposable pytest directory for content-addressed snapshots.
    """
    suite = review_bundle["suite"]
    result = register_dataset(
        name=suite["name"], dataset_name=review_bundle["dataset_name"],
        assistant=suite["assistant"], description=suite["description"],
        items_path=MANIFEST, database=suite["database"], max_turns=suite["max_turns"],
        snapshots=tmp_path,
    )
    imported = load_snapshot(result["snapshot"], tmp_path)

    assert result["created"] is True
    assert result["item_count"] == len(CASE_PAGES)
    assert imported["items"] == review_bundle["items"]
    assert imported["suite"]["assistant"] == "unit_expert"
    assert imported["suite"]["max_turns"] == 40
    assert imported["suite"]["managed_workflow"] is True
    validate_case_semantics(imported["suite"], imported["items"])
