"""Validate authored-content parity, conflict handling, and hosted version freezing."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote

import pytest

from evals.langfuse.content import (export_snapshot, fetch_bundle, load_catalog,
                                    load_snapshot, seed_content,
                                    validate_bundle)
from evals.langfuse.utils import catalog_revision
from domain.assistants.constants import AssistantName

ROOT = Path(__file__).resolve().parents[1] / "snapshots"


class Missing(Exception):
    """Represent an explicit remote 404 in SDK-independent tests."""
    status_code = 404


class FakeClient:
    """Model Langfuse dataset upserts and mutable UI-owned content."""

    def __init__(self):
        """Initialize a fresh project without datasets or prompts."""
        self.datasets = {}
        self.prompts = {}
        self.read_versions = []
        self.api = SimpleNamespace(prompts=SimpleNamespace(get=self.get_prompt))

    def get_prompt(self, name, **kwargs):
        """Read the requested prompt version after decoding its API path."""
        name = unquote(name)
        if name not in self.prompts:
            raise Missing()
        return deepcopy(self.prompts[name])

    def create_prompt(self, name, prompt, **kwargs):
        """Create a baseline text prompt for initial project seeding."""
        self.prompts[name] = SimpleNamespace(name=name, prompt=prompt, version=1)

    def get_dataset(self, name, **kwargs):
        """Return isolated dataset state and record frozen read timestamps."""
        if name not in self.datasets:
            raise Missing()
        self.read_versions.append(kwargs.get("version"))
        return deepcopy(self.datasets[name])

    def create_dataset(self, name, description=None, metadata=None, **kwargs):
        """Upsert dataset metadata while preserving existing cases."""
        if name not in self.datasets:
            self.datasets[name] = SimpleNamespace(id=name, name=name, items=[])
        self.datasets[name].metadata = metadata
        self.datasets[name].description = description
        return self.datasets[name]

    def create_dataset_item(self, dataset_name, **kwargs):
        """Append a seeded case with its global remote identifier."""
        self.datasets[dataset_name].items.append(SimpleNamespace(**{"status": "ACTIVE", **deepcopy(kwargs)}))


def fixture_bundle():
    """Load the committed passing fixture definition without legacy dependencies."""
    return load_snapshot("12919b463fd2b4bd5fdda2765fe6f7745191fcd4668a062576ff8a923f493591", ROOT)


def test_committed_inventory_preserves_authored_checks():
    """Keep all authored cases, grading weights, and the empty suite visible."""
    entries = load_catalog(ROOT)
    bundles = [load_snapshot(e["snapshot"], ROOT) for e in entries]
    assert len(entries) == 14
    assert sum(len(b["items"]) for b in bundles) == 153
    experts = {b["suite"]["name"]: b for b in bundles if "expert" in b["suite"]["name"]}
    assert {name: len(bundle["items"]) for name, bundle in experts.items()} == {
        "comp-expert": 18, "item-expert": 17, "meta-expert": 0,
        "trait-expert": 17, "unit-expert": 17,
    }
    assert sum(len(item["metadata"].get("deterministic_checks", []))
               for bundle in experts.values() for item in bundle["items"]) == 162
    assertions = [
        assertion
        for bundle in bundles
        if bundle["suite"].get("scoring") != "none"
        for item in bundle["items"]
        if item.get("metadata", {}).get("scoring") != "none"
        for assertion in (item["metadata"]["legacy_definition"]["expected_output"]["assertions"]
                          if "legacy_definition" in item.get("metadata", {})
                          else item.get("metadata", {}).get("deterministic_checks", [])
                          if bundle["schema_version"] >= 2
                          else item["expected_output"]["assertions"])
    ]
    assert sum(a["kind"] == "trace" for a in assertions) == 248
    assert sum(a["kind"] == "rubric" for a in assertions) == 13
    assert next(b for b in bundles if b["suite"]["name"] == AssistantName.ANALYZE_TRANSCRIPT)["items"] == []
    assert all("file://" not in json.dumps(b) for b in bundles)
    assert next(a for a in assertions if a.get("selector") == "payload_reduction")["threshold"] == .75


def test_baseline_snapshots_retain_complete_authored_content():
    """Keep the accepted migration artifacts immutable after platform cutover."""
    baseline_ids = [
        "f2e033f4ff79af6d19561def78be48e878c316d10b62a7ea281abad0a03fc532",
        "89ea8bff65b228961027da487bd4f69d8a014f49ebb2894f14688ddcd657821a",
        "c927d07be966f4d7c2c53a80a369cba4cbf4cfe7833d8b1959839e83ff062d7c",
        "4ac53489862d17447488c399f047384565bb91bdf6bf50b9af62fad99b67d888",
        "aaf6d5f43a6fd32e80a88270b495099bc766b8dbd0e1c05f15ccd89d408d9e08",
        "548ed5b704124f3d59fc4a097b4c8246ee54f1a76a889009e9ebb138764fb099",
        "9eeaa3d2c7624fe920cad5e8194386e72728a09a72d6b995771e1128b3bcbe84",
        "bc613ff033405bb733b4a7b052cd785858f0ffce416ce98689b410b7eba09e90",
    ]
    bundles = [load_snapshot(identifier, ROOT) for identifier in baseline_ids]
    items = [item for bundle in bundles for item in bundle["items"]]
    assert len(items) == 54 and len({item["id"] for item in items}) == 54
    assertions = [assertion for item in items for assertion in item["expected_output"]["assertions"]]
    rubrics = [assertion for assertion in assertions if assertion["kind"] == "rubric"]
    assert len(rubrics) == 15
    assert all(assertion["weight"] == 1 and assertion["threshold"] == .8 for assertion in rubrics)
    assert all(isinstance(item["input"]["input"], str) for item in items)
    for bundle in bundles:
        assert "chattft/judge" == bundle["prompts"]["judge"]["name"]
        assert all(prompt["text"] and prompt["version"] == 1 for prompt in bundle["prompts"].values())


def test_snapshot_hash_integrity_and_catalog_conflicts(tmp_path):
    """Reuse identical content and reject stale catalogs and changed snapshots."""
    bundle = fixture_bundle()
    revision = catalog_revision(tmp_path)
    identifier = export_snapshot(bundle, tmp_path, revision)
    assert export_snapshot(bundle, tmp_path) == identifier
    with pytest.raises(ValueError, match="catalog changed"):
        export_snapshot(bundle, tmp_path, revision)
    with pytest.raises(ValueError, match="SHA-256"):
        load_snapshot("../../etc/passwd", tmp_path)
    (tmp_path / f"{identifier}.json").write_text("{}")
    with pytest.raises(ValueError, match="contents"):
        load_snapshot(identifier, tmp_path)


def test_ui_edits_archives_and_deletions_survive_reseeding(tmp_path):
    """Repeated initialization never overwrites UI edits or resurrects deleted cases."""
    export_snapshot(fixture_bundle(), tmp_path)
    client = FakeClient()
    first = seed_content(client, tmp_path)
    assert first["datasets"] == 1 and first["items"] == 1
    client.prompts[f"chattft/assistants/{AssistantName.CHAT}"].prompt = "UI candidate"
    item = client.datasets[f"chattft/{AssistantName.DUMMY_ASSISTANT}"].items[0]
    item.input["input"] = "UI-edited question"
    item.status = "ARCHIVED"
    assert seed_content(client, tmp_path) == {"datasets": 0, "items": 0, "prompts": 0}
    assert client.datasets[f"chattft/{AssistantName.DUMMY_ASSISTANT}"].items[0].input["input"] == "UI-edited question"
    client.datasets[f"chattft/{AssistantName.DUMMY_ASSISTANT}"].items.clear()
    seed_content(client, tmp_path)
    assert client.datasets[f"chattft/{AssistantName.DUMMY_ASSISTANT}"].items == []
    assert client.prompts[f"chattft/assistants/{AssistantName.CHAT}"].prompt == "UI candidate"


def test_freeze_captures_remote_identity_and_versions(tmp_path):
    """Capture UI content once and isolate it from subsequent hosted edits."""
    export_snapshot(fixture_bundle(), tmp_path)
    client = FakeClient()
    seed_content(client, tmp_path)
    client.prompts[f"chattft/assistants/{AssistantName.CHAT}"].version = 7
    client.prompts[f"chattft/assistants/{AssistantName.CHAT}"].resolution_graph = {"child": {"version": 2}}
    frozen = fetch_bundle(client, f"chattft/{AssistantName.DUMMY_ASSISTANT}", {"dataset_version": "2026-09-13T00:00:00Z"}, tmp_path)
    assert frozen["dataset_id"] == f"chattft/{AssistantName.DUMMY_ASSISTANT}"
    assert frozen["items"][0]["remote_id"]
    assert frozen["prompts"][AssistantName.CHAT]["version"] == 7
    assert frozen["prompts"][AssistantName.CHAT]["resolution_graph"]["child"]["version"] == 2
    assert client.read_versions[-1].isoformat() == "2026-09-13T00:00:00+00:00"
    client.datasets[f"chattft/{AssistantName.DUMMY_ASSISTANT}"].items[0].input["input"] = "later edit"
    client.prompts[f"chattft/assistants/{AssistantName.CHAT}"].prompt = "later prompt"
    assert frozen["items"][0]["input"]["input"] != "later edit"
    assert frozen["prompts"][AssistantName.CHAT]["text"] != "later prompt"


def test_malformed_ui_checks_fail_before_execution():
    """Reject unknown check implementations and invalid thresholds before enqueueing."""
    bundle = fixture_bundle()
    bundle["items"][0]["expected_output"]["assertions"][0]["check"]["type"] = "custom-code"
    with pytest.raises(ValueError, match="unsupported trace"):
        validate_bundle(bundle)
    bundle = fixture_bundle()
    bundle["items"][0]["expected_output"]["assertions"][0]["weight"] = float("nan")
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_remote_failures_are_not_treated_as_missing_content(tmp_path):
    """Avoid accidental reseeding when authentication or platform availability fails."""
    export_snapshot(fixture_bundle(), tmp_path)
    client = FakeClient()
    def unavailable(*args, **kwargs):
        """Simulate a platform outage instead of a content-not-found response."""
        raise ConnectionError("platform unavailable")
    client.get_prompt = unavailable
    with pytest.raises(ConnectionError):
        seed_content(client, tmp_path)
    assert client.datasets == {}


def test_frozen_config_rejects_unresolved_candidates_and_invalid_limits():
    """Local snapshot replay enforces the same controls as browser submissions."""
    bundle = fixture_bundle()
    bundle["config"]["concurrency"] = 5
    with pytest.raises(ValueError):
        validate_bundle(bundle)
    bundle = fixture_bundle()
    bundle["config"]["variants"][0]["prompts"] = {AssistantName.CHAT: {"name": f"chattft/assistants/{AssistantName.CHAT}", "label": "latest"}}
    with pytest.raises(ValueError, match="resolved"):
        validate_bundle(bundle)


def test_invalid_catalog_edits_are_rejected(tmp_path):
    """Protect exported routing metadata from conflicts with its immutable bundle."""
    export_snapshot(fixture_bundle(), tmp_path)
    catalog = json.loads((tmp_path / "catalog.json").read_text())
    catalog["suites"][0]["assistant"] = "different_agent"
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="conflicts"):
        load_catalog(tmp_path)


@pytest.mark.parametrize("field,value", [("input", "plain text"), ("expected_output", []), ("metadata", "invalid")])
def test_malformed_ui_item_shapes_report_validation_errors(field, value):
    """UI JSON edits report actionable validation errors without starting work."""
    bundle = fixture_bundle()
    bundle["items"][0][field] = value
    with pytest.raises(ValueError):
        validate_bundle(bundle)


def test_context_response_smoke_seeds_thirty_cases_without_overwriting_ui(tmp_path):
    """Transfer the new natural suite with stable identities and preserve later edits."""
    source = Path(__file__).resolve().parents[2] / "datasets/context_response_smoke.json"
    bundle = json.loads(source.read_text())
    export_snapshot(bundle, tmp_path)
    client = FakeClient()
    counts = seed_content(client, tmp_path, natural=True)
    assert counts["datasets"] == 1 and counts["items"] == 30
    dataset = client.datasets["context-response"]
    assert [item.input for item in dataset.items] == [item["input"] for item in bundle["items"]]
    assert all(len(item.metadata["deterministic_checks"]) == 1 for item in dataset.items)
    assert all(item.metadata["quality_profile"] is None for item in dataset.items)
    dataset.items[0].input = "Edited in Langfuse"
    assert seed_content(client, tmp_path, natural=True) == {"datasets": 0, "items": 0, "prompts": 0}
    assert dataset.items[0].input == "Edited in Langfuse"
