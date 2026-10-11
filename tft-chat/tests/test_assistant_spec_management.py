"""Exercise spec lifecycle safety without changing real assistants or Langfuse."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.assistant_specs.main import create_spec, remove_spec
from evals.langfuse import prompts


@pytest.fixture
def specs(tmp_path, monkeypatch):
    """Provide isolated specs and avoid runtime tool imports during file tests."""
    import domain.assistants

    root = tmp_path / "specs"
    root.mkdir()
    monkeypatch.setattr(domain.assistants, "resolve_assistant_tools", lambda spec: [])
    create_spec(root, "old_expert", prompt="Explain the evidence.")
    return root


def test_create_copy_and_recoverable_removal(specs, tmp_path):
    """Copy optional files and preserve the complete removed directory in a backup."""
    (specs / "old_expert/task.md").write_text("Analyze: {input}")
    (specs / "old_expert/notes.txt").write_text("Preserve this too.")
    create_spec(specs, "new_expert", copy_from="old_expert", prompt="New behavior.")
    assert (specs / "new_expert/system.md").read_text() == "New behavior."
    assert (specs / "new_expert/task.md").read_text().strip() == "Analyze: {input}"
    assert json.loads((specs / "new_expert/agent.json").read_text())["name"] == "new_expert"
    assert not (specs / "new_expert/notes.txt").exists()
    assert remove_spec(specs, tmp_path, "old_expert")["blockers"] == []
    assert (specs / "old_expert").exists()
    result = remove_spec(specs, tmp_path, "old_expert", apply=True, backup_dir=tmp_path / "backups")
    assert not (specs / "old_expert").exists()
    assert (Path(result["backup"]) / "notes.txt").read_text() == "Preserve this too."


@pytest.mark.parametrize("name", ["../outside", "/tmp/outside", "", "AGENTS", "judge", "old_expert"])
def test_creation_rejects_unsafe_and_existing_names(specs, name):
    """Never escape the spec root or overwrite an existing assistant."""
    with pytest.raises(ValueError):
        create_spec(specs, name, prompt="Instructions.")
    assert (specs / "old_expert/system.md").read_text() == "Explain the evidence."


def test_removal_reports_handoffs_callers_and_suites(specs, tmp_path):
    """Refuse deletion until runtime and eval dependencies have been migrated."""
    create_spec(specs, "router", prompt="Route requests.")
    (specs / "router/agent.json").write_text(json.dumps({"handoffs": ["old_expert"]}))
    caller = tmp_path / "app/backend/caller.py"
    caller.parent.mkdir(parents=True)
    caller.write_text('run("old_expert")\n# "old_expert" in comments is not a caller\n')
    catalog = tmp_path / "evals/langfuse/snapshots"
    catalog.mkdir(parents=True)
    (catalog / "catalog.json").write_text(json.dumps({"suites": [
        {"name": "expert_eval", "assistant": "old_expert", "snapshot": "fixture"}]}))
    (catalog / "fixture.json").write_text(json.dumps({"config": {}, "items": []}))
    result = remove_spec(specs, tmp_path, "old_expert")
    assert len(result["blockers"]) == 3
    with pytest.raises(ValueError, match="dependencies"):
        remove_spec(specs, tmp_path, "old_expert", apply=True, backup_dir=tmp_path / "backup")
    assert (specs / "old_expert").exists()


def test_removal_rejects_symlinks_and_nested_backup(specs, tmp_path):
    """Keep removal confined to a real source directory with an external backup."""
    with pytest.raises(ValueError, match="outside"):
        remove_spec(specs, tmp_path, "old_expert", apply=True, backup_dir=specs / "backup")
    (specs / "old_expert/link").symlink_to(tmp_path / "unrelated")
    with pytest.raises(ValueError, match="symbolic link"):
        remove_spec(specs, tmp_path, "old_expert")


class PromptWorkspace:
    """Fake versioned public prompt transport with observable writes."""

    def __init__(self):
        """Start with one edited active prompt and two retired versions."""
        self.rows = {
            "chattft/assistants/active": [{"name": "chattft/assistants/active", "version": 1,
                                          "prompt": "Authored in Langfuse", "labels": ["baseline"]}],
            "chattft/assistants/retired": [{"name": "chattft/assistants/retired", "version": version,
                                           "prompt": f"Old {version}", "labels": ["baseline"]}
                                          for version in (1, 2)],
        }
        self.writes = []

    def list(self, path):
        """Enumerate existing prompts and concrete versions."""
        return [{"name": name, "versions": [row["version"] for row in rows]}
                for name, rows in self.rows.items() if rows]

    def request(self, method, path, **kwargs):
        """Read, create, or delete individual versions like the public endpoint."""
        from urllib.parse import unquote

        name = unquote(path.removeprefix("v2/prompts/"))
        if method == "GET":
            return deepcopy(next(row for row in self.rows[name] if row["version"] == kwargs["params"]["version"]))
        self.writes.append((method, path, kwargs))
        if method == "POST":
            value = {**kwargs["json"], "version": 1}
            self.rows[value["name"]] = [value]
        elif method == "DELETE":
            self.rows[name] = [row for row in self.rows[name] if row["version"] != kwargs["params"]["version"]]


@pytest.fixture
def prompt_workspace(monkeypatch):
    """Use an explicit tiny desired inventory for remote reconciliation tests."""
    monkeypatch.setattr(prompts, "repository_prompts", lambda: {
        name: {"name": f"chattft/assistants/{name}", "text": "Repository instructions"}
        for name in ("active", "new")})
    return PromptWorkspace()


def test_prompt_sync_preview_backup_and_idempotence(prompt_workspace, tmp_path):
    """Preview writes, back up all versions, and preserve authored active content."""
    plan = prompts.sync_prompts(remove=["retired"], workspace=prompt_workspace)
    assert plan["create"] == ["chattft/assistants/new"]
    assert plan["remove"] == ["chattft/assistants/retired"]
    assert prompt_workspace.writes == []
    with pytest.raises(ValueError, match="backup-dir"):
        prompts.sync_prompts(remove=["retired"], apply=True, workspace=prompt_workspace)
    result = prompts.sync_prompts(remove=["retired"], apply=True,
                                  backup_dir=tmp_path, workspace=prompt_workspace)
    assert len(json.loads((Path(result["backup"]) / "prompts.json").read_text())) == 2
    assert len(result["deleted_versions"]) == 2
    assert prompt_workspace.rows["chattft/assistants/active"][0]["prompt"] == "Authored in Langfuse"
    repeated = prompts.sync_prompts(remove=["retired"], apply=True, workspace=prompt_workspace)
    assert repeated["create"] == repeated["remove"] == []


def test_prompt_sync_blocks_active_and_composed_dependencies(prompt_workspace, tmp_path):
    """Reject active-spec deletion and dependencies in any retained prompt version."""
    with pytest.raises(ValueError, match="repository spec"):
        prompts.sync_prompts(remove=["active"], apply=True, workspace=prompt_workspace)
    prompt_workspace.rows["chattft/assistants/active"][0]["prompt"] = "@@@langfusePrompt:name=chattft/assistants/retired|version=1@@@"
    with pytest.raises(ValueError, match="references"):
        prompts.sync_prompts(remove=["retired"], apply=True, backup_dir=tmp_path, workspace=prompt_workspace)
    assert prompt_workspace.writes == []


def test_natural_seed_uses_current_specs_not_snapshot_prompts(monkeypatch, tmp_path):
    """Retired snapshot prompts stay absent while new repository prompts are seeded."""
    from evals.langfuse.content import export_snapshot, seed_content
    from evals.langfuse.tests.test_content import FakeClient, fixture_bundle

    bundle = fixture_bundle()
    bundle["items"] = []
    export_snapshot(bundle, tmp_path)
    monkeypatch.setattr(prompts, "repository_prompts", lambda: {
        "new": {"name": "chattft/assistants/new", "text": "Current instructions"}})
    client = FakeClient()
    assert seed_content(client, tmp_path, natural=True, include_fixtures=True)["prompts"] == 1
    assert set(client.prompts) == {"chattft/assistants/new"}
    client.prompts["chattft/assistants/new"].prompt = "UI edit"
    assert seed_content(client, tmp_path, natural=True, include_fixtures=True)["prompts"] == 0
    assert client.prompts["chattft/assistants/new"].prompt == "UI edit"


def test_experiment_prompts_follow_current_graph(monkeypatch):
    """Freeze new handoff targets without retaining unrelated retired prompts."""
    import domain.assistants

    monkeypatch.setattr(domain.assistants, "reload_assistant_specs", lambda: None)
    monkeypatch.setattr(domain.assistants, "assistant_handoff_names", lambda name: ["new"] if name == "active" else [])
    monkeypatch.setattr(prompts, "repository_prompts", lambda: {
        name: {"name": f"chattft/assistants/{name}"} for name in ("active", "new", "unrelated")})
    assert set(prompts.experiment_prompts({"assistant": "active", "execution": "live"})) == {"active", "new"}


def test_partial_remote_failure_retains_backup_and_journal(prompt_workspace, tmp_path, monkeypatch):
    """A failed second deletion records the first without losing recovery definitions."""
    import httpx

    request = prompt_workspace.request

    def fail_second_delete(method, path, **kwargs):
        """Simulate a transport failure after one version was successfully removed."""
        if method == "DELETE" and kwargs["params"]["version"] == 2:
            raise httpx.ConnectError("private upstream details")
        return request(method, path, **kwargs)

    monkeypatch.setattr(prompt_workspace, "request", fail_second_delete)
    with pytest.raises(ValueError, match="journal.json") as error:
        prompts.sync_prompts(remove=["retired"], apply=True, backup_dir=tmp_path, workspace=prompt_workspace)
    assert "private upstream details" not in str(error.value)
    backup = next(tmp_path.iterdir())
    assert len(json.loads((backup / "prompts.json").read_text())) == 2
    journal = json.loads((backup / "journal.json").read_text())
    assert journal["deleted_versions"] == [{"name": "chattft/assistants/retired", "version": 1}]
    assert journal["applied"] is False


def test_empty_successful_delete_response():
    """Accept Langfuse's empty successful deletion response without a false failure."""
    import httpx
    from evals.langfuse.workspace import Workspace

    workspace = Workspace("http://test", "public", "secret")
    workspace.http.close()
    workspace.http = httpx.Client(base_url="http://test", transport=httpx.MockTransport(
        lambda request: httpx.Response(204)))
    try:
        assert workspace.request("DELETE", "v2/prompts/test") is None
    finally:
        workspace.close()


def test_natural_fetch_does_not_request_retired_snapshot_prompts(monkeypatch, tmp_path):
    """Export a live bundle with new graph prompts even when old ones were deleted."""
    from types import SimpleNamespace
    from evals.langfuse import utils
    from evals.langfuse.content import export_snapshot, fetch_bundle
    from evals.langfuse.tests.test_content import FakeClient

    suite = {"name": "chat", "assistant": "chat", "family": "assistant",
             "execution": "live", "description": "Prompt inventory regression", "scoring": "none"}
    schemas = {"input": {"type": "string"}, "expected_output": None}
    export_snapshot({"schema_version": 3, "suite": suite, "schemas": schemas,
                     "dataset_name": "end-to-end", "items": [], "config": utils.default_config(),
                     "prompts": {"retired": {"name": "chattft/assistants/retired", "version": 1,
                                             "text": "Old frozen instructions"}}}, tmp_path)
    client = FakeClient()
    client.datasets["end-to-end"] = SimpleNamespace(id="dataset", items=[],
        metadata={"contract_version": 3}, input_schema=schemas["input"], expected_output_schema=None)
    desired = {name: {"name": f"chattft/assistants/{name}"} for name in ("chat", "new")}
    for row in desired.values():
        client.create_prompt(row["name"], "Current baseline")
    monkeypatch.setattr(prompts, "experiment_prompts", lambda suite: desired)
    monkeypatch.setattr(utils, "configured_native_workspace", lambda: SimpleNamespace(
        items=lambda *args, **kwargs: [], close=lambda: None))
    frozen = fetch_bundle(client, "end-to-end", {}, tmp_path)
    graph = frozen['execution']['graphs']['Active']
    assert set(frozen['prompts']) == set(graph['specs'])
    assert 'retired' not in frozen['prompts'] and 'new' not in frozen['prompts']
    assert frozen['prompts']['chat']['text'] == graph['specs']['chat']['system_prompt']
    assert all('/workspace/' in row['name'] for row in frozen['prompts'].values())
    assert client.prompts['chattft/assistants/new'].prompt == 'Current baseline'
