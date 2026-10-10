"""Verify local registration, optional JSON intake, and hosted seeding."""

from __future__ import annotations

import json

import pytest

from evals.langfuse.content import fetch_bundle, load_catalog, load_snapshot, seed_content
from evals.langfuse.dataset_registration import register_dataset
from evals.langfuse.grading import seed_grading
from evals.langfuse.tests.test_content import FakeClient
from evals.langfuse.utils import default_config
from domain.assistants.constants import AssistantName


def test_register_dataset_seeds_json_cases_and_keeps_ui_edits(tmp_path):
    """A registered suite seeds once and lets Langfuse own later case edits."""
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"items": [
        {"case": "scored", "input": "Rank four-cost units.",
         "expected_output": {"requirements": ["Include sample sizes."]},
         "metadata": {"database": "set_database"}},
        {"case": "intake", "input": "Explore this idea.",
         "metadata": {"scoring": "none"}},
    ]}))
    snapshots = tmp_path / "snapshots"
    first = register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
        assistant=AssistantName.CHAT, description="Manual investigations.", items_path=cases,
        database=None, max_turns=10, snapshots=snapshots)
    bundle = load_snapshot(first["snapshot"], snapshots)
    assert load_catalog(snapshots)[0]["managed_workflow"] is True
    assert [item["id"] for item in bundle["items"]] == [
        "manual_probe/scored", "manual_probe/intake"]
    assert bundle["items"][0]["metadata"]["quality_profile"] == "answer_quality"
    assert bundle["items"][1]["expected_output"] is None
    assert "quality_profile" not in bundle["items"][1]["metadata"]

    client = FakeClient()
    assert seed_content(client, snapshots, natural=True)["items"] == 2
    hosted = client.datasets["chattft/manual-probe"]
    assert hosted.metadata["contract_version"] == 3
    hosted.items[0].input = "Edited in Langfuse."
    assert seed_content(client, snapshots, natural=True) == {
        "datasets": 0, "items": 0, "prompts": 0}
    assert hosted.items[0].input == "Edited in Langfuse."
    again = register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
        assistant=AssistantName.CHAT, description="Manual investigations.", items_path=cases,
        database=None, max_turns=10, snapshots=snapshots)
    assert again["created"] is False


@pytest.mark.parametrize("items", [
    [{"case": "bad", "input": {"text": "not a string"}, "expected_output": "x"}],
    [{"case": "bad", "input": "Question", "expected_output": None}],
    [{"case": "bad", "input": "Question", "expected_output": "x",
      "metadata": {"database": "postgresql://server/database"}}],
])
def test_invalid_initial_items_leave_catalog_untouched(tmp_path, items):
    """Reject bad inputs, missing grading references, and connection strings."""
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(items))
    snapshots = tmp_path / "snapshots"
    with pytest.raises(ValueError):
        register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
            assistant=AssistantName.CHAT, description="Manual investigations.", items_path=cases,
            database=None, max_turns=10, snapshots=snapshots)
    assert not (snapshots / "catalog.json").exists()


def test_grading_adds_managed_dataset_without_resetting_rule(monkeypatch, tmp_path):
    """A registered dataset joins native rule filters while UI settings survive."""
    from evals.langfuse import grading

    class Workspace:
        """Capture only native rule changes needed by the seeding operation."""

        def __init__(self):
            """Keep the preserved rule and its write history."""
            self.patches = []

        def list(self, path, **kwargs):
            """Supply an existing provider without other platform resources."""
            return [{"provider": "openai"}] if path == "llm-connections" else []

        def request(self, method, path, **kwargs):
            """Record public rule patches for assertions."""
            self.patches.append((method, path, kwargs["json"]))
            return {}

    def resource(workspace, existing, path, name, identity, definition):
        """Model previously configured rules and newly referenced resources."""
        if path == "v2/evaluation-rules":
            return {"id": name, "filter": [
                {"column": "datasetId", "value": ["existing-id"]},
                {"column": "metadata", "key": "custom", "value": "keep"},
            ]}
        return {"id": name}

    monkeypatch.setattr(grading, "ensure_resource", resource)
    workspace = Workspace()
    seed_grading(workspace, [
        {"id": "existing-id", "name": "end-to-end"},
        {"id": "new-id", "name": "chattft/manual-probe"},
    ], tmp_path / "grading.json", model="judge", api_key="unused",
        managed_names={"chattft/manual-probe"})
    assert len(workspace.patches) == 5
    assert all(body["filter"] == [
        {"column": "datasetId", "value": ["existing-id", "new-id"]},
        {"column": "metadata", "key": "custom", "value": "keep"},
    ] for _, _, body in workspace.patches)


@pytest.mark.parametrize("assistant", [None, AssistantName.UNIT_EXPERT])
def test_registered_dataset_reaches_frozen_experiment_bundle(monkeypatch, tmp_path, assistant):
    """The webhook freezes hosted cases and the run's selected entry assistant."""
    from evals.langfuse import grading, prompts, utils

    snapshots = tmp_path / "snapshots"
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"case": "probe", "input": "Explain this cohort.",
        "expected_output": {"requirements": ["Use the scoped population."]}}]))
    register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
        assistant=AssistantName.CHAT, description="Manual investigations.", items_path=cases,
        database=None, max_turns=10, snapshots=snapshots)
    client = FakeClient()
    seed_content(client, snapshots, natural=True)
    hosted = client.datasets["chattft/manual-probe"]
    hosted.input_schema = {"type": "string"}
    hosted.expected_output_schema = None

    class Native:
        """Return hosted item versions in the pinned native API shape."""

        def items(self, dataset_id, *, version=None):
            """Read the one seeded case without external services."""
            return [{"id": item.id, "status": item.status, "input": item.input,
                     "expectedOutput": item.expected_output, "metadata": item.metadata,
                     "createdAt": "2026-01-01T00:00:00Z",
                     "updatedAt": "2026-01-01T00:00:00Z"} for item in hosted.items]

        def close(self):
            """Close the fake native transport."""

    class Workspace:
        """Stand in for the grading-definition read."""

        def close(self):
            """Close the fake grading transport."""

    monkeypatch.setattr(utils, "configured_native_workspace", Native)
    monkeypatch.setattr(utils, "configured_workspace", Workspace)
    monkeypatch.setattr(utils, "load_grading_registry", lambda: {})
    monkeypatch.setattr(grading, "freeze_grading", lambda workspace, registry: {})
    selected = []
    def inventory(suite):
        """Capture the assistant used to discover the prompt graph."""
        selected.append(suite["assistant"])
        return {}
    monkeypatch.setattr(prompts, "experiment_prompts", inventory)
    config = {**default_config(), "assistant": assistant} if assistant else default_config()
    bundle = fetch_bundle(client, "chattft/manual-probe", config, snapshots)
    assert bundle["dataset_name"] == "chattft/manual-probe"
    assert bundle["suite"]["assistant"] == AssistantName.CHAT
    assert bundle["config"].get("assistant") == assistant
    assert selected == [assistant or AssistantName.CHAT]
    assert bundle["items"][0]["id"] == "manual_probe/probe"
    assert bundle["items"][0]["metadata"]["quality_profile"] == "answer_quality"


def test_run_assistant_selection_validates_prompt_targets():
    """Run JSON accepts registered roots and limits candidates to their graph."""
    from evals.langfuse.utils import validate_frozen_config

    suite = {"family": "assistant", "execution": "live", "assistant": AssistantName.CHAT}
    config = {**default_config(), "assistant": AssistantName.UNIT_EXPERT}
    config["variants"][0]["prompts"] = {AssistantName.UNIT_EXPERT: {
        "name": f"chattft/assistants/{AssistantName.UNIT_EXPERT}", "version": 1, "text": "Test prompt."}}
    validate_frozen_config(config, suite)
    config["variants"][0]["prompts"] = {AssistantName.CHAT: {
        "name": f"chattft/assistants/{AssistantName.CHAT}", "version": 1, "text": "Test prompt."}}
    with pytest.raises(ValueError, match="unreachable assistants"):
        validate_frozen_config(config, suite)
    config["variants"][0]["prompts"] = {}
    config["assistant"] = "does_not_exist"
    with pytest.raises(ValueError, match="Unknown assistant"):
        validate_frozen_config(config, suite)


def test_run_bundle_passes_selected_assistant_to_task(tmp_path):
    """Execution uses the run override while retaining the dataset default."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from unittest.mock import Mock
    from evals.langfuse.experiments import run_bundle

    snapshots = tmp_path / "snapshots"
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps([{"case": "probe", "input": "Name one unit.",
        "metadata": {"scoring": "none"}}]))
    registered = register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
        assistant=AssistantName.CHAT, description="Manual investigations.", items_path=cases,
        database=None, max_turns=10, snapshots=snapshots)
    bundle = load_snapshot(registered["snapshot"], snapshots)
    bundle["config"]["assistant"] = AssistantName.UNIT_EXPERT
    bundle.update(dataset_id="dataset", dataset_version=datetime.now(timezone.utc).isoformat())
    bundle["items"][0]["remote_id"] = "remote-case"
    bundle["suite"]["scoring"] = "none"
    client = Mock()
    client.get_dataset.return_value = SimpleNamespace(id="dataset")
    client.run_experiment.return_value = SimpleNamespace(
        dataset_run_id=None, dataset_run_url="", item_results=[])
    run_bundle(bundle, client=client)
    task = client.run_experiment.call_args.kwargs["task"]
    assert bundle["suite"]["assistant"] == AssistantName.CHAT
    assert task.keywords["suite"]["assistant"] == AssistantName.UNIT_EXPERT


def test_pending_jobs_prevent_runner_restarts(tmp_path):
    """Dataset registration can guard work awaiting execution or scoring."""
    from evals.langfuse.jobs import JobStore

    jobs = JobStore(tmp_path)
    assert not jobs.has_pending()
    job_id = jobs.submit({"case": "one"}, "snapshot")
    assert jobs.has_pending()
    jobs.finish(job_id, "completed")
    assert not jobs.has_pending()


def test_registered_dataset_gets_authenticated_custom_experiment(monkeypatch, tmp_path):
    """Native seeding targets the catalog name and preserves bearer routing."""
    from evals.langfuse import seed

    snapshots = tmp_path / "snapshots"
    register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
        assistant=AssistantName.CHAT, description="Manual investigations.", items_path=None,
        database=None, max_turns=10, snapshots=snapshots)
    client = FakeClient()
    seed_content(client, snapshots, natural=True)
    calls = []

    class Native:
        """Capture the configured remote experiment without a live workspace."""

        def __init__(self, *args):
            """Accept owner credentials without storing their values."""

        def call(self, operation, body, *, read=False):
            """Return no existing button, then record its creation."""
            if operation == "upsertRemoteExperiment":
                calls.append(body)
            return None

        def close(self):
            """Close the fake owner session."""

    monkeypatch.setattr(seed, "NativeWorkspace", Native)
    assert seed.configure_triggers(client, snapshots, base_url="http://local",
        email="owner", password="private", token="secret") == 1
    assert calls[0]["url"] == "http://experiments/experiments"
    assert calls[0]["requestHeaders"]["Authorization"] == {
        "value": "Bearer secret", "secret": True}


def test_registration_rejects_unrelated_existing_dataset(tmp_path):
    """A same-name UI dataset without the runner contract cannot appear ready."""
    snapshots = tmp_path / "snapshots"
    register_dataset(name="manual_probe", dataset_name="chattft/manual-probe",
        assistant=AssistantName.CHAT, description="Manual investigations.", items_path=None,
        database=None, max_turns=10, snapshots=snapshots)
    client = FakeClient()
    client.create_dataset(name="chattft/manual-probe", metadata={})
    with pytest.raises(ValueError, match="lacks the ChatTFT string-item contract"):
        seed_content(client, snapshots, natural=True)
