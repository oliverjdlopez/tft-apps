"""Verify durable argument-only exports without models or a live platform."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from evals.langfuse.artifacts import render_run_artifact, write_run_artifact
from evals.langfuse.jobs import JobStore
from evals.langfuse.server import ExperimentService
from evals.langfuse.utils import artifact_execution_fields
from domain.assistants.constants import AssistantName


@pytest.fixture
def run_records():
    """Provide frozen selected inputs and two distinct experiment responses."""
    bundle = {"schema_version": 3, "dataset_name": "unit-expert", "suite": {"name": "unit-expert"},
              "config": {"cases": ["unit/a", "unit/b"]}, "items": [
                  {"id": "unit/a", "input": "Exact prompt\n\nSecond paragraph."},
                  {"id": "unit/b", "input": "Failed prompt"},
                  {"id": "unit/other", "input": "UNSELECTED"},
                  {"id": "unit/archived", "input": "ARCHIVED", "status": "ARCHIVED"}]}
    captured = {"metadata": {"tft_trace": {"tool_calls": [
        {"name": "compare_cohorts", "arguments": json.dumps({
            "target": {"units": [{"name": "Veigar", "star_level": 3}]},
            "shared": None, "enabled": False, "range": [0, 20]}),
         "agent": AssistantName.UNIT_EXPERT, "output": "PRIVATE TOOL RETURN"}]}}}
    row = {"id": "unit/a", "result": "**Exact response**\n\nNo paraphrasing.",
           **artifact_execution_fields(captured)}
    report = {"passed": False, "state": "awaiting_scores", "experiments": [
        {"name": "baseline r1", "dataset_run_id": "run-one", "items": [row,
         {"id": "unit/b", "result": "", "execution_error": "Timeout after 180 seconds", "tool_calls": None}]},
        {"name": "candidate r2", "dataset_run_id": "run-two", "items": [
            {**deepcopy(row), "result": "Different final answer", "tool_calls": []}]}]}
    return bundle, report


def test_grading_checkpoint_survives_restart_then_exports(run_records, tmp_path):
    """Terminal completion exports checkpointed arguments without remote recovery."""
    bundle, report = run_records
    jobs = JobStore(tmp_path)
    job_id = jobs.submit(bundle, "snapshot", awaiting_result=report)
    assert not (tmp_path / "artifacts").exists()
    restarted = JobStore(tmp_path)
    waiting = restarted.pending_scores()[0]
    waiting["result"].update(state="completed", passed=False)
    restarted.finish(job_id, "failed", result=waiting["result"])
    saved = restarted.get(job_id)
    artifact = saved["result"]["markdown_artifact"]
    assert saved["state"] == "failed" and artifact["status"] == "written"
    text = Path(artifact["path"]).read_text()
    assert text.count(bundle["items"][0]["input"]) == 2
    assert report["experiments"][0]["items"][0]["result"] in text
    assert text.index("#### Final output") < text.index("#### Tool trace")
    assert "Different final answer" in text and "run\\-two" in text
    assert "**target**" in text and "**star\\_level**: `3`" in text
    assert "**shared**: Not set (`null`)" in text and "**enabled**: `false`" in text
    assert "No final response recorded" in text and "Timeout after 180 seconds" in text
    assert "Tool arguments were not captured" in text and "No tool calls recorded" in text
    assert all(value not in text for value in ("PRIVATE TOOL RETURN", "UNSELECTED", "ARCHIVED", "```json"))
    assert "PRIVATE TOOL RETURN" not in json.dumps(saved)
    restarted.finish(job_id, "failed", result=waiting["result"])
    assert len(list((tmp_path / "artifacts").glob("*.md"))) == 1


def test_export_failure_preserves_run_outcome(run_records, tmp_path, monkeypatch):
    """An unwritable artifact does not turn an evaluation pass into a failure."""
    from evals.langfuse import artifacts
    bundle, report = run_records
    report.update(state="completed", passed=True)
    monkeypatch.setattr(artifacts, "atomic_write", Mock(side_effect=OSError("disk full")))
    jobs = JobStore(tmp_path)
    job_id = jobs.submit(bundle, "snapshot")
    jobs.finish(job_id, "completed", result=report)
    saved = jobs.get(job_id)
    assert saved["state"] == "completed" and saved["result"]["passed"]
    assert saved["result"]["markdown_artifact"] == {"status": "failed", "error": "OSError: disk full"}


def test_early_failure_and_export_only(run_records, tmp_path):
    """Early failures retain selected prompts; export-only requests never render."""
    bundle, _ = run_records
    jobs = JobStore(tmp_path)
    export_id = jobs.submit(bundle, "snapshot", exported=True)
    assert jobs.get(export_id)["state"] == "exported"
    assert not (tmp_path / "artifacts").exists()
    job_id = jobs.submit(bundle, "snapshot")
    jobs.finish(job_id, "failed", error="Execution unavailable")
    text = Path(jobs.get(job_id)["result"]["markdown_artifact"]["path"]).read_text()
    assert "Execution unavailable" in text and text.count("No final response recorded") == 2


@pytest.mark.parametrize("graded", [False, True])
def test_service_completion_writes_artifact(run_records, tmp_path, monkeypatch, graded):
    """Both immediate and asynchronous service completion reach the export hook."""
    from evals.langfuse import experiments, grading
    bundle, report = run_records
    service = ExperimentService(tmp_path / "snapshots", tmp_path / "runtime", Mock)
    service.client = Mock()
    service.workspace = Mock()
    bundle["grading"] = {}
    report["grading_deadline"] = 9999999999
    job_id = service.jobs.submit(bundle, "snapshot", awaiting_result=report if graded else None)

    def complete(*args, **kwargs):
        """Finish one consumer iteration without external services."""
        service.stop.set()
        return {**report, "state": "completed"}

    monkeypatch.setattr(experiments, "run_bundle", complete)
    monkeypatch.setattr(grading, "reconcile_report", complete)
    service.consume()
    saved = service.jobs.get(job_id)
    assert Path(saved["result"]["markdown_artifact"]["path"]).is_file()
    assert service.client.create_event.call_args.kwargs["output"]["result"]["markdown_artifact"]["status"] == "written"


def test_structured_output_is_not_mistaken_for_execution_wrapper(run_records):
    """Natural outputs may legitimately contain metadata or error-named fields."""
    bundle, report = run_records
    report["experiments"][0]["items"][0]["result"] = {"metadata": "answer field", "output": "value", "error": False}
    text = render_run_artifact(bundle, report, state="failed")
    assert "**metadata**: answer field" in text and "**error**: `false`" in text


def test_unsafe_identity_and_malformed_arguments(run_records, tmp_path):
    """Filenames stay beneath runtime and malformed captured arguments remain visible."""
    bundle, report = run_records
    report["experiments"][0]["items"][0]["tool_calls"][0]["arguments"] = '<broken *args*'
    write_run_artifact(bundle, report, tmp_path, "../../outside", state="failed")
    path = Path(report["markdown_artifact"]["path"])
    assert path.parent == tmp_path
    assert 'Arguments were not valid JSON' in path.read_text()
    assert '&lt;broken \\*args\\*' in path.read_text()
    with pytest.raises(ValueError, match="terminal"):
        write_run_artifact(bundle, report, tmp_path, "pending", state="awaiting_scores")


def test_offline_cli_runs_real_fixture_and_exports(tmp_path, monkeypatch, capsys):
    """The ordinary CLI path writes a report after a credential-free fixture run."""
    from evals.langfuse import launcher
    from evals.langfuse.content import export_snapshot, load_snapshot
    bundle = load_snapshot("548ed5b704124f3d59fc4a097b4c8246ee54f1a76a889009e9ebb138764fb099",
                           launcher.SNAPSHOT_ROOT)
    snapshots = tmp_path / "snapshots"
    snapshots.mkdir()
    export_snapshot(bundle, snapshots)
    monkeypatch.setattr(launcher, "SNAPSHOT_ROOT", snapshots)
    monkeypatch.setenv("LANGFUSE_RUNTIME_DIR", str(tmp_path / "runtime"))
    assert launcher.run(AssistantName.DUMMY_ASSISTANT, offline=True) == 0
    report = json.loads(capsys.readouterr().out)
    artifact = report["markdown_artifact"]
    text = Path(artifact["path"]).read_text()
    assert artifact["status"] == "written"
    assert report["experiments"][0]["items"][0]["result"]["output"] in text
    assert "#### Tool trace" in text
