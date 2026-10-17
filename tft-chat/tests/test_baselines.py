"""Regression selection stays stable while native exports remain editable."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from evals.baselines import MANIFEST, ROOT, authored_contract, validate_baselines
from evals.langfuse.content import export_snapshot, load_snapshot


@pytest.fixture
def baseline(tmp_path):
    """Build a private source, manifest, and immutable snapshot directory."""
    registry = json.loads(MANIFEST.read_text())
    entry = next(row for row in registry["suites"] if row["suite"] == "context_response_smoke")
    bundle = load_snapshot(entry["snapshot"], ROOT / "langfuse/snapshots")
    snapshot = export_snapshot(bundle, tmp_path / "snapshots")
    (tmp_path / "source.json").write_text(json.dumps(bundle))
    manifest = tmp_path / "baselines.json"
    manifest.write_text(json.dumps({"schema_version": 1, "suites": [{"suite": "context_response_smoke", "source": "source.json", "snapshot": snapshot}]}))
    return manifest, bundle


def test_export_noise_does_not_change_authored_semantics(baseline):
    """Export timestamps, remote IDs, and item order are not grading changes."""
    manifest, bundle = baseline
    source = deepcopy(bundle)
    source["items"].reverse()
    source["dataset_version"] = "later"
    source["items"][0]["remote_id"] = "remote"
    source["execution"] = {"unrelated": "transport metadata"}
    assert authored_contract(source) == authored_contract(bundle)
    assert validate_baselines(manifest, manifest.parent / "snapshots")


@pytest.mark.parametrize("damage", ["input", "grading", "missing", "duplicate", "hash"])
def test_corrupt_baselines_cannot_pass(baseline, damage):
    """Reject altered grading, dropped identities, and invalid immutable references."""
    manifest, bundle = baseline
    if damage == "input":
        bundle["items"][0]["input"] = "Different question"
    elif damage == "grading":
        bundle["items"][0]["metadata"]["placeholder_checks"] = True
    elif damage == "missing":
        bundle["items"].pop()
    elif damage == "duplicate":
        bundle["items"].append(deepcopy(bundle["items"][0]))
    else:
        value = json.loads(manifest.read_text())
        value["suites"][0]["snapshot"] = "missing"
        manifest.write_text(json.dumps(value))
    (manifest.parent / "source.json").write_text(json.dumps(bundle))
    with pytest.raises(ValueError):
        validate_baselines(manifest, manifest.parent / "snapshots")


def test_latest_ui_export_cannot_replace_pinned_regressions(baseline):
    """A changed native catalog remains independent of reviewed baseline selection."""
    manifest, bundle = baseline
    original = validate_baselines(manifest, manifest.parent / "snapshots")
    bundle["items"][0]["input"] = "Native UI edit"
    export_snapshot(bundle, manifest.parent / "snapshots")
    assert validate_baselines(manifest, manifest.parent / "snapshots") == original


def test_live_baseline_prepares_current_graph_without_spending_tokens(monkeypatch):
    """Exercise the exact dispatch entry point while replacing the paid boundary."""
    from evals import baseline_run
    from evals.assistant_execution import require_bundle_captures
    observed = []

    def fake_run(suite, snapshot, data_snapshot_label):
        """Inspect the effective immutable bundle immediately before dispatch."""
        bundle = load_snapshot(snapshot, baseline_run.launcher.SNAPSHOT_ROOT)
        require_bundle_captures(bundle)
        assert bundle["suite"]["name"] == suite == "context_response_smoke"
        assert data_snapshot_label == "synthetic"
        assert not any(item["metadata"]["placeholder_checks"] for item in bundle["items"])
        observed.append(snapshot)
        return 0

    monkeypatch.setattr(baseline_run.launcher, "run", fake_run)
    assert baseline_run.run("context_response_smoke", "synthetic") == 0
    assert len(observed) == 1
