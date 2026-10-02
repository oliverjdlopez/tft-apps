"""Validate authored datasets through ChatTFT's importer without registration.

Only the brainstorming validation report and combined dataset are written. The
actual importer's catalog read and snapshot export are replaced in memory, so
its item normalization and validators run without changing application state.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import unquote
from unittest.mock import patch

import domain.assistants  # Initialize registry before importing dependent eval modules.
from domain.tools import get_tool
from evals.langfuse import dataset_registration
from evals.langfuse.content import validate_bundle
from evals.langfuse.utils import validate_case_semantics
from evals.models import EvalTrace, Handoff, ToolCall, TraceEvent
from evals.trace import evaluate_trace_check
from jsonschema import Draft202012Validator
from artifact_validation.utils import partial_schema


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(__file__).resolve().parents[1]


def check_trace_assertion(assertion: dict) -> dict:
    """Exercise one authored deterministic check with synthetic trace witnesses.

    Args:
        assertion: Existing ChatTFT trace assertion containing a check object.

    Returns:
        Validation counts and the kinds of witnesses checked; no real run claim.
    """
    config = assertion["check"]
    kind = config["type"]
    values = config.get("values", config.get("value", []))
    names = [values] if isinstance(values, str) else values
    name = names[0] if names else ""
    actor = config.get("agent")
    arguments = deepcopy(config.get("arguments", {}))
    schemas_checked = 0
    if kind in {"tool_called", "tool_argument_resolved"} and arguments:
        acceptable = []
        for target in names:
            validator = Draft202012Validator(partial_schema(get_tool(target).params_json_schema))
            errors = list(validator.iter_errors(arguments))
            if not errors:
                acceptable.append(target)
        if not acceptable:
            raise ValueError(f"{assertion['name']}: arguments fit no registered alternative: {arguments}")
        name = acceptable[0]
        schemas_checked = len(acceptable)
    positive = EvalTrace()
    negative = EvalTrace()
    if kind == "tool_called":
        count = config.get("min_count", 1)
        calls = [ToolCall(name=name, arguments=json.dumps(arguments), agent=actor) for _ in range(count)]
        prior = config.get("after_handoff")
        events = ([TraceEvent(type="handoff", source="chat", target=prior)] if prior else [])
        events += [TraceEvent(type="tool_call", tool=name, agent=actor) for _ in range(count)]
        positive = EvalTrace(tool_calls=calls, events=events)
    elif kind == "tool_argument_resolved":
        fields = config["argument"]
        fields = [fields] if isinstance(fields, str) else fields
        for target in names:
            properties = get_tool(target).params_json_schema["properties"]
            if not any(field in properties for field in fields):
                raise ValueError(f"{assertion['name']}: resolved flow has no valid top-level field for {target}")
        arguments[fields[0]] = "SyntheticResolvedName"
        resolution = ToolCall(name="resolve_tft_names", agent=actor,
                              arguments=json.dumps({"names": [config["query"]]}),
                              output=json.dumps({"results": [{"query": config["query"], "resolved": True,
                                                               "matches": [{"name": "SyntheticResolvedName"}]}]}))
        downstream = ToolCall(name=name, agent=actor, arguments=json.dumps(arguments))
        positive = EvalTrace(tool_calls=[resolution, downstream])
        negative = EvalTrace(tool_calls=[downstream, resolution])
    elif kind == "handoff_to":
        positive = EvalTrace(handoffs=[Handoff(source="chat", target=name)])
    elif kind == "final_agent":
        positive = EvalTrace(final_agent=name)
    elif kind == "tool_not_called":
        negative = EvalTrace(tool_calls=[ToolCall(name=name)])
    elif kind == "no_handoff":
        negative = EvalTrace(handoffs=[Handoff(source="chat", target="data_analyst")])
    elif kind == "regex":
        # Regex correctness is checked by repository validation. No invented
        # answer is synthesized as evidence that a gameplay regex is meaningful.
        return {"type": kind, "schema_alternatives_checked": schemas_checked, "witness": "repository_regex_validation_only"}
    else:
        raise ValueError(f"Unsupported authored check kind: {kind}")
    if not evaluate_trace_check(config, positive).passed:
        raise ValueError(f"{assertion['name']}: positive synthetic witness did not pass")
    if evaluate_trace_check(config, negative).passed:
        raise ValueError(f"{assertion['name']}: negative synthetic witness passed")
    return {"type": kind, "schema_alternatives_checked": schemas_checked, "witness": "positive_and_negative"}


def validate_import(path: Path, suite_name: str) -> dict:
    """Run importer normalization and semantic checks with all exports intercepted.

    Args:
        path: Lane or combined import JSON inside this brainstorming directory.
        suite_name: Temporary in-memory suite identity for validation only.

    Returns:
        Normalized item/check counts and assertion witness reports.
    """
    captured = []

    def capture_export(bundle: dict, snapshots: Path) -> str:
        """Capture the validated definition instead of writing any snapshot.

        Args:
            bundle: Importer's normalized bundle.
            snapshots: Ignored destination; no directory is created.

        Returns:
            An in-memory content identity, never registered in a catalog.
        """
        captured.append(validate_bundle(bundle))
        return hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()

    with patch.object(dataset_registration, "load_catalog", return_value=[]), patch.object(dataset_registration, "export_snapshot", side_effect=capture_export):
        dataset_registration.register_dataset(
            name=suite_name, dataset_name="chattft/" + suite_name, assistant="chat",
            description="Brainstorming validation only", items_path=path,
            database=None, max_turns=40, snapshots=RUN / "validation/NEVER_WRITTEN",
        )
    assert len(captured) == 1
    bundle = captured[0]
    validate_case_semantics(bundle["suite"], bundle["items"])
    traces = []
    for item in bundle["items"]:
        metadata = item["metadata"]
        assert metadata["source_case_id"] == metadata["case"]
        assert metadata["quality_profile"] == "answer_quality"
        assert metadata["grading_scope"] == "investigation_behavior_and_answer_coverage"
        assert metadata["numeric_ground_truth_verified"] is False
        assert "database" not in metadata or metadata["database"] is None
        assert metadata.get("scoring") != "none"
        requirements = item["expected_output"]["requirements"]
        assert len(requirements) >= 3 and all(isinstance(x, str) and x.strip() for x in requirements)
        for assertion in metadata.get("deterministic_checks", []):
            traces.append({"case": metadata["case"], "name": assertion["name"], **check_trace_assertion(assertion)})
    return {"items": len(bundle["items"]), "checks": len(traces), "assertions": traces,
            "import_normalization": "passed_with_export_intercepted", "semantic_validation": "passed"}


def verify_preservation() -> dict:
    """Compare original research and source fingerprints without touching Git state.

    Returns:
        File counts and unexpected changes; authorized registration hashes are
        verified separately without replacing the original authoring baseline.
    """
    baseline = json.loads((RUN / "validation/baseline.json").read_text())
    receipt = RUN / "validation/langfuse-integration.json"
    authorized = json.loads(receipt.read_text()).get("authorized_repository_changes", {}) if receipt.exists() else {}
    # Registration explicitly expanded the original brainstorming-only boundary.
    # Permit exactly these non-source files, and only at their verified hashes.
    assert set(authorized) <= {
        "evals/langfuse/snapshots/catalog.json",
        "docs/development/langfuse-content.md",
    }
    changed = []
    for group in ("original_files", "source_files"):
        for relative, digest in baseline[group].items():
            path = ROOT / relative
            expected = authorized.get(relative, digest)
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                changed.append(relative)
    return {"original_research_files": len(baseline["original_files"]),
            "source_documentation_eval_test_files": len(baseline["source_files"]),
            "authorized_integration_changes": sorted(authorized),
            "changed_paths": changed}


def validate_artifact_links() -> dict:
    """Check local Markdown destinations in the completed brainstorming run.

    Returns:
        Link counts and missing destinations without checking external websites.
    """
    checked = 0
    missing = []
    for document in RUN.rglob("*.md"):
        for destination in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text()):
            destination = destination.strip().strip("<>")
            if "://" in destination or destination.startswith("#"):
                continue
            target = unquote(destination.split("#", 1)[0])
            if not target:
                continue
            checked += 1
            if not (document.parent / target).resolve().exists():
                missing.append({"document": str(document.relative_to(RUN)), "target": target})
    return {"local_links_checked": checked, "missing": missing}


def main() -> None:
    """Validate all available lane artifacts and assemble only a complete corpus."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--partial", action="store_true")
    arguments = parser.parse_args()
    manifest = json.loads((RUN / "manifest.json").read_text())
    reports = []
    missing = []
    combined = []
    for lane in manifest["lanes"]:
        directory = RUN / lane["directory"]
        path = directory / "dataset.json"
        if not path.exists():
            missing.append(lane["lane"])
            continue
        data = json.loads(path.read_text())
        identifiers = [item.get("case", item.get("metadata", {}).get("case")) for item in data["items"]]
        assert len(identifiers) == len(set(identifiers))
        assert set(identifiers) == set(lane["cases"]), (lane["lane"], identifiers)
        source_cases = json.loads((directory / "reconciled-cases.json").read_text())["cases"]
        for item, case in zip(data["items"], source_cases):
            assert item["case"] == case["id"], "Keep original lane case order"
            assert item["input"].startswith(case["question"]), case["id"]
            assert "status" not in item or item["status"] == "ACTIVE"
            metadata = item["metadata"]
            for field in ("lane", "subject", "source_case_file", "source_status", "source_answer_status", "proposal_lineage", "data_readiness"):
                assert metadata[field] == case[field], (case["id"], field)
            assert metadata["set_number"] == 18
            assert metadata["queue_context"] == "standard_ranked"
            assert "Set 18 standard-ranked" in item["input"]
        assert (directory / "authoring-report.md").is_file()
        try:
            report = validate_import(path, "brainstorm_" + lane["lane"].lower().replace("-", "_"))
        except Exception as error:
            raise ValueError(f"{lane['lane']} import/assertion validation failed: {error}") from error
        reports.append({"lane": lane["lane"], **report})
        combined.extend(data["items"])
    if missing and not arguments.partial:
        raise ValueError(f"Missing lane datasets: {missing}")
    preservation = verify_preservation()
    assert not preservation["changed_paths"], preservation
    report = {"scope": "offline_definition_validation_not_live_model_or_database_execution",
              "lanes": reports, "missing_lanes": missing,
              "case_count": len(combined), "check_count": sum(lane["checks"] for lane in reports),
              "preservation": preservation,
              "registration_performed": False, "live_evaluation_performed": False,
              "numerical_gold_verified": False}
    if not missing:
        assert len(combined) == manifest["case_count"] == 69
        assert len({item["case"] for item in combined}) == 69
        destination = RUN / "dataset.json"
        destination.write_text(json.dumps({"items": combined}, indent=2, ensure_ascii=False) + "\n")
        report["combined_validation"] = validate_import(destination, "set18_grounded_investigations")
        assert json.loads(destination.read_text())["items"] == combined
        report["artifact_links"] = validate_artifact_links()
        assert not report["artifact_links"]["missing"], report["artifact_links"]
        lineages = {lineage for item in combined for lineage in item["metadata"]["proposal_lineage"]}
        original_lineages = {lineage for case in json.loads((RUN / "source-lineage.json").read_text())
                             for lineage in case["source_index_entry"].get("proposal_lineage", [])}
        assert lineages == original_lineages
        report["preserved_proposal_lineages"] = len(lineages)
    (RUN / "validation/dataset-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"validated_lanes": len(reports), "cases": len(combined), "checks": report["check_count"], "missing": missing, "source_changes": preservation["changed_paths"]}))


if __name__ == "__main__":
    main()
