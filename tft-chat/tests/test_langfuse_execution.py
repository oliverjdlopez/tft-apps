"""Neutral execution and frozen native experiment contracts."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import execution, worker
from evals.langfuse.content import load_snapshot
from evals.langfuse.experiments import run_bundle
from evals.utils import eval_graph_instructions, render_judge_prompt
from domain.assistants.constants import AssistantName


@pytest.fixture
def fixture_bundle():
    """Load the real migrated offline suite for adapter parity checks."""
    root = Path(__file__).resolve().parents[1] / "evals/langfuse/snapshots"
    # UI exports advance the catalog; unit parity uses the accepted baseline.
    return load_snapshot("548ed5b704124f3d59fc4a097b4c8246ee54f1a76a889009e9ebb138764fb099", root)


def test_fixture_five_authored_checks_and_variant_repetitions(fixture_bundle):
    """Every variant/repetition preserves the real five-check credential-free fixture."""
    fixture_bundle["config"]["variants"] = [{"name": "a", "prompts": {}}, {"name": "b", "prompts": {}}]
    fixture_bundle["config"]["repetitions"] = 2
    report = run_bundle(fixture_bundle)
    assert report["passed"] and len(report["experiments"]) == 4
    assert len(report["experiments"][0]["items"][0]["scores"]) == 7


def test_weighted_score_cannot_hide_assertion_failure(fixture_bundle):
    """A high weighted mean cannot override a required assertion's failure."""
    item = fixture_bundle["items"][0]
    item["expected_output"]["assertions"][0]["weight"] = 100
    result = execution.execute_attempt(fixture_bundle["suite"], item, {}, {})
    result["metadata"].pop("tft_trace")
    scores = execution.score_attempt(item, result, {})
    assert scores[-2]["value"] > .9
    assert scores[-1]["value"] == 0


def test_errors_and_missing_assertions_never_pass(fixture_bundle):
    """Execution errors remain failures even when all thresholds are zero."""
    item = fixture_bundle["items"][0]
    for assertion in item["expected_output"]["assertions"]:
        assertion["threshold"] = 0
    assert execution.score_attempt(item, {"error": "timeout"}, {})[-1]["value"] == 0
    item["expected_output"]["assertions"] = []
    assert execution.score_attempt(item, {"output": "ok"}, {})[-1]["value"] == 0


def test_judge_error_and_bad_score_fail(monkeypatch, fixture_bundle):
    """Bad grader responses fail rather than treating zero-threshold cases as passing."""
    item = fixture_bundle["items"][0]
    item["expected_output"]["assertions"] = [{"kind": "rubric", "name": "quality", "rubric": "accurate", "threshold": 0, "weight": 1}]
    for response in ({"error": "judge timeout"}, {"output": '{"score": NaN, "reason": "broken"}'}):
        monkeypatch.setattr(execution, "isolated_operation", lambda *args: response)
        scores = execution.score_attempt(item, {"output": "answer"}, {"judge": {"text": "{{rubric}} {{output}}"}})
        assert not scores[0]["passed"] and scores[-1]["value"] == 0


def test_judge_template_substitution_is_single_pass(fixture_bundle):
    """Literal template-looking user output cannot interpolate a rubric twice."""
    rendered = render_judge_prompt("{{rubric}}\n{{output}}", fixture_bundle["items"][0], {"output": "{{rubric}}"}, "judge this")
    assert rendered.count("judge this") == 1
    assert "{{rubric}}" in rendered


def test_graph_candidates_use_each_targets_instruction_policy(monkeypatch):
    """Graph overrides retain target-specific dynamic context assembly."""
    import domain.assistants as assistants
    seen = []
    monkeypatch.setattr(assistants, "assistant_handoff_names", lambda name: ["child"] if name == "root" else [])
    def assemble(name, query, *, base_instructions):
        """Record policy calls while returning distinguishable context text."""
        seen.append((name, query, base_instructions))
        return f"{base_instructions}:{name}-context"
    monkeypatch.setattr(assistants, "build_assistant_instructions", assemble)
    result = eval_graph_instructions("root", "request", {"root": {"text": "root-v2"}, "child": {"text": "child-v3"}})
    assert result == {"root": "root-v2:root-context", "child": "child-v3:child-context"}
    assert len(seen) == 2


def test_neutral_worker_protocol(monkeypatch):
    """Neutral worker requests use operation, config, input, and identity."""
    monkeypatch.setattr(worker, "run_judge", lambda prompt, config: {"output": prompt})
    assert worker.execute({"operation": "judge", "config": {"family": "judge"}, "input": {"input": "grade"}}) == {"output": "grade"}


def test_native_sdk_receives_frozen_hosted_items(fixture_bundle):
    """Native dataset IDs and version survive without refetching edited UI content."""
    pytest.importorskip("langfuse")
    fixture_bundle.update(dataset_id="dataset", dataset_name=f"chattft/{AssistantName.DUMMY_ASSISTANT}", dataset_version="2026-09-13T00:00:00+00:00")
    fixture_bundle["items"][0]["remote_id"] = "remote-item"
    original = deepcopy(fixture_bundle)
    class Client:
        """Record exact SDK arguments without HTTP or model calls."""
        def get_dataset(self, name):
            """Verify platform identity without consulting current item contents."""
            return SimpleNamespace(id="dataset", items=[])
        def run_experiment(self, **kwargs):
            """Execute the supplied task and evaluator against frozen SDK objects."""
            assert kwargs["data"][0].id == "remote-item"
            assert kwargs["data"][0].dataset_id == "dataset"
            assert kwargs["_dataset_version"].year == 2026
            item = kwargs["data"][0]
            output = kwargs["task"](item=item)
            scores = kwargs["evaluators"][0](input=item.input, output=output, expected_output=item.expected_output, metadata=item.metadata)
            return SimpleNamespace(item_results=[SimpleNamespace(item=item, output=output, evaluations=scores, trace_id="trace", dataset_run_id="run")], dataset_run_id="run", dataset_run_url="http://local/run")
        def update_current_span(self, **kwargs):
            """Accept fixture evidence metadata."""
        def flush(self):
            """Provide the SDK flushing contract."""
    report = run_bundle(fixture_bundle, Client())
    assert report["passed"] and report["experiments"][0]["dataset_run_id"] == "run"
    assert report["experiments"][0]["url"] == "http://localhost:15510/run"
    assert fixture_bundle == original
    exported_item = report["experiments"][0]["items"][0]
    assert exported_item["result"]["output"]
    assert len(exported_item["scores"]) == 7
    assert exported_item["scores"][-1]["passed"]


def test_unscored_native_dataset_runs_without_evaluators(monkeypatch):
    """Execution-only intake publishes outputs without manufacturing scores."""
    pytest.importorskip("langfuse")
    from evals.langfuse import experiments

    bundle = {
        "schema_version": 2,
        "suite": {"name": "chat_intake", "assistant": AssistantName.CHAT, "family": "assistant",
                  "execution": "live", "scoring": "none", "database": None,
                  "description": "Unscored prompt intake.", "max_turns": 7},
        "dataset_id": "intake-dataset",
        "dataset_name": "chattft/intake/unscored-prompts",
        "dataset_version": "2026-09-16T00:00:00+00:00",
        "schemas": {"input": {"type": "object"}, "expected_output": None},
        "items": [{"id": "chat_intake/case", "remote_id": "remote-item",
                   "input": {"messages": [{"role": "user", "content": "Question"}]},
                   "expected_output": None,
                   "metadata": {"suite": "chat_intake", "case": "case",
                                "case_id": "chat_intake/case"}, "status": "ACTIVE"}],
        "prompts": {AssistantName.CHAT: {"name": f"chattft/assistants/{AssistantName.CHAT}", "version": 1,
                              "text": "Answer the request."}},
        "config": {"action": "run", "cases": [], "variants": [{"name": "baseline",
                                                                    "model": None, "prompts": {}}],
                   "dataset_version": None, "concurrency": 1, "repetitions": 1,
                   "selection_live": False, "data_snapshot_label": None, "snapshot": None},
    }
    monkeypatch.setattr(experiments, "execute_attempt", lambda *args: {
        "output": "Unscored answer", "metadata": {"tft_trace": {"tool_calls": [
            {"name": "resolve_tft_names", "arguments": '{"names":["Veigar"]}',
             "agent": AssistantName.CHAT, "call_id": "call-1", "output": "PRIVATE TOOL RETURN"}]}}, "token_usage": {}})

    class Client:
        """Execute the SDK callbacks while recording the evaluator contract."""

        def get_dataset(self, name):
            """Return the matching hosted dataset identity."""
            return SimpleNamespace(id="intake-dataset", items=[])

        def run_experiment(self, **kwargs):
            """Run one task and require the evaluator list to remain empty."""
            assert kwargs["evaluators"] == []
            item = kwargs["data"][0]
            output = kwargs["task"](item=item)
            row = SimpleNamespace(item=item, output=output, evaluations=[], trace_id="trace",
                                  dataset_run_id="run")
            return SimpleNamespace(item_results=[row], dataset_run_id="run",
                                   dataset_run_url="http://local/run")

        def update_current_span(self, **kwargs):
            """Accept execution metadata emitted by the task callback."""

        def flush(self):
            """Provide the SDK flushing contract."""

    report = run_bundle(bundle, Client())
    assert report["passed"] and report.get("state") is None
    item = report["experiments"][0]["items"][0]
    assert item["scores"] == [] and item["execution_success"] and item["scoring"] == "none"
    assert item["tool_calls"][0]["arguments"] == '{"names":["Veigar"]}'
    assert "PRIVATE TOOL RETURN" not in json.dumps(report)
    assert not item["result_is_execution_wrapper"]


def test_portable_snapshot_binds_only_identities(fixture_bundle):
    """Seeding a fresh platform does not replace a portable snapshot's old inputs."""
    from evals.langfuse.experiments import bind_dataset_identity
    from datetime import datetime, timezone
    from unittest.mock import Mock
    for key in ("dataset_id", "dataset_name", "dataset_version"):
        fixture_bundle.pop(key, None)
    for item in fixture_bundle["items"]:
        item.pop("remote_id", None)
    original = deepcopy(fixture_bundle)
    item = fixture_bundle["items"][0]
    client = Mock()
    client.api.prompts.get.return_value = SimpleNamespace(name="changed", version=1, prompt="different destination text", resolution_graph=None)
    client.get_dataset.return_value = SimpleNamespace(id="new-dataset", version=datetime.now(timezone.utc), items=[
        SimpleNamespace(id="new-remote-item", metadata={"case_id": item["id"]}, input={"input": "edited later"})])
    bound = bind_dataset_identity(fixture_bundle, client)
    assert bound["items"][0]["remote_id"] == "new-remote-item"
    assert bound["items"][0]["input"] == original["items"][0]["input"]
    assert fixture_bundle == original


def test_complete_hosted_snapshot_rebinds_on_a_fresh_platform(fixture_bundle):
    """Exports carrying old platform IDs remain runnable after seeding fresh CI."""
    from evals.langfuse.experiments import bind_dataset_identity
    from datetime import datetime, timezone
    from unittest.mock import Mock
    fixture_bundle.update(dataset_id="old-dataset", dataset_name=f"chattft/{AssistantName.DUMMY_ASSISTANT}",
                          dataset_version="2025-01-01T00:00:00+00:00")
    fixture_bundle["items"][0]["remote_id"] = "old-remote-item"
    original = deepcopy(fixture_bundle)
    version = datetime(2026, 9, 13, tzinfo=timezone.utc)
    client = Mock()
    client.api.prompts.get.return_value = SimpleNamespace(name="changed", version=1, prompt="different destination text", resolution_graph=None)
    client.get_dataset.return_value = SimpleNamespace(id="new-dataset", version=version, items=[
        SimpleNamespace(id="new-remote-item", metadata={"case_id": fixture_bundle["items"][0]["id"]},
                        input={"input": "later changed UI input"}, expected_output={"assertions": []})])
    bound = bind_dataset_identity(fixture_bundle, client)
    assert bound["dataset_id"] == "new-dataset"
    assert bound["dataset_version"] == version.isoformat()
    assert bound["items"][0]["remote_id"] == "new-remote-item"
    assert bound["items"][0]["input"] == original["items"][0]["input"]
    assert bound["items"][0]["expected_output"] == original["items"][0]["expected_output"]
    assert bound["prompts"] == original["prompts"]
    assert bound["source_dataset"]["dataset_id"] == "old-dataset"
    assert fixture_bundle == original


def test_same_platform_replay_retains_historical_deleted_case(fixture_bundle):
    """Current dataset edits and deletions cannot replace same-platform history."""
    from evals.langfuse.experiments import bind_dataset_identity
    from unittest.mock import Mock
    fixture_bundle.update(dataset_id="same", dataset_name=f"chattft/{AssistantName.DUMMY_ASSISTANT}",
                          dataset_version="2025-01-01T00:00:00+00:00")
    fixture_bundle["items"][0]["remote_id"] = "deleted-in-current-version"
    client = Mock()
    client.get_dataset.return_value = SimpleNamespace(id="same", items=[])
    assert bind_dataset_identity(fixture_bundle, client) == fixture_bundle


@pytest.mark.parametrize("matches", [True, False])
def test_relocated_prompt_links_only_matching_destination_text(matches):
    """A new platform may link version one without mislabeling the source version."""
    pytest.importorskip("langfuse")
    from unittest.mock import Mock
    from evals.langfuse.experiments import bind_prompt_references
    from evals.utils import frozen_langfuse_prompt, prompt_reference_key
    source = {"name": f"chattft/assistants/{AssistantName.CHAT}", "version": 4, "text": "exact frozen candidate"}
    bundle = {"prompts": {AssistantName.CHAT: source}, "config": {"variants": [{"prompts": {}}]}}
    original = deepcopy(bundle)
    client = Mock()
    client.api.prompts.get.return_value = SimpleNamespace(
        name=source["name"], version=1, prompt=source["text"] if matches else "different UI candidate",
        resolution_graph=None)
    references = bind_prompt_references(bundle, client)
    linked = frozen_langfuse_prompt({**source, "native_reference": references[prompt_reference_key(source)]})
    if matches:
        assert linked.version == 1 and linked.prompt == source["text"]
    else:
        assert linked is None
    assert bundle == original and source["version"] == 4


def test_export_bundle_never_runs(fixture_bundle, monkeypatch):
    """An accidental dispatch of an export-only definition starts no operations."""
    from unittest.mock import Mock
    fixture_bundle["config"]["action"] = "export"
    operation = Mock()
    monkeypatch.setattr(execution, "isolated_operation", operation)
    with pytest.raises(ValueError, match="Export-only"):
        run_bundle(fixture_bundle)
    operation.assert_not_called()


def test_native_generation_links_frozen_prompt_without_fetch(monkeypatch):
    """A live-shaped attempt references its exact candidate version without HTTP."""
    pytest.importorskip("langfuse")
    from contextlib import nullcontext
    from unittest.mock import Mock
    from evals.langfuse import experiments
    client = Mock()
    client.start_as_current_observation.return_value = nullcontext()
    monkeypatch.setattr(experiments, "execute_attempt", lambda *args: {
        "output": "answer", "metadata": {"model": "test", "instruction_hashes": {AssistantName.CHAT: "hash"}},
        "token_usage": {"prompt": 8, "completion": 2, "total": 10},
    })
    baseline = {"name": f"chattft/assistants/{AssistantName.CHAT}", "version": 1, "text": "old"}
    candidate = {"name": f"chattft/assistants/{AssistantName.CHAT}", "version": 3, "text": "candidate"}
    handoff = {"name": f"chattft/assistants/{AssistantName.DATA_ANALYST}", "version": 2, "text": "handoff"}
    experiments.run_item_task(item={"input": {"input": "request"}}, suite={"assistant": AssistantName.CHAT},
                              variant={"prompts": {AssistantName.CHAT: candidate, AssistantName.DATA_ANALYST: handoff}},
                              prompts={AssistantName.CHAT: baseline}, client=client)
    linked = client.start_as_current_observation.call_args.kwargs["prompt"]
    assert linked.name == candidate["name"] and linked.version == 3
    assert linked.prompt == "candidate" and not linked.is_fallback
    metadata = client.update_current_span.call_args.kwargs["metadata"]
    assert metadata["prompt_versions"][AssistantName.DATA_ANALYST]["version"] == 2
    client.get_prompt.assert_not_called()


@pytest.mark.parametrize("natural", [False, True])
def test_case_databases_reach_isolated_workers_without_leaking(monkeypatch, natural):
    """Mixed-set cases keep their own target across attempts and preserve defaults."""
    suite = {"name": AssistantName.CHAT, "family": "assistant", "execution": "live", "database": "suite_db"}
    calls = []

    def capture(payload, timeout):
        """Capture dispatch without connecting to a model or database."""
        calls.append(deepcopy(payload))
        return {"output": "answer"}

    monkeypatch.setattr(execution, "isolated_operation", capture)
    for database in ("old_set", "new_set", None):
        item = {"input": {"messages": [{"role": "user", "content": "question"}]} if natural else {"input": "question"},
                "expected_output": {"requirements": []} if natural else {"assertions": []},
                "metadata": {"database": database}}
        original = deepcopy(item)
        for variant in ({"name": "baseline"}, {"name": "candidate"}):
            result = execution.execute_attempt(suite, item, variant, {})
            assert "error" not in result
        assert item == original
    assert [call["config"]["database"] for call in calls] == [
        "old_set", "old_set", "new_set", "new_set", "suite_db", "suite_db"]
    assert suite["database"] == "suite_db"
    suite.pop("database")
    execution.execute_attempt(suite, item, {}, {})
    assert calls[-1]["config"]["database"] is None


@pytest.mark.parametrize("database", ["", "  ", 42, {}, "postgresql://host/db", "host=server dbname=db", "db\n"])
def test_invalid_case_database_fails_before_worker(monkeypatch, database):
    """Malformed targets cannot launch a worker or silently use a default."""
    from unittest.mock import Mock
    dispatch = Mock()
    monkeypatch.setattr(execution, "isolated_operation", dispatch)
    result = execution.execute_attempt(
        {"family": "assistant", "execution": "live"},
        {"input": {"input": "question"}, "metadata": {"database": database}}, {}, {})
    assert "plain database name" in result["error"]
    dispatch.assert_not_called()


@pytest.mark.parametrize("natural", [False, True])
def test_case_database_survives_snapshot_round_trip(tmp_path, fixture_bundle, natural):
    """Frozen database choices remain replayable without rewriting old snapshots."""
    from evals.langfuse.content import export_snapshot, validate_bundle
    if natural:
        from evals.langfuse.contracts import migrate_bundle
        fixture_bundle = migrate_bundle(fixture_bundle)
    fixture_bundle["items"][0]["metadata"]["database"] = "old_set"
    snapshot = export_snapshot(fixture_bundle, tmp_path)
    restored = load_snapshot(snapshot, tmp_path)
    assert restored["items"][0]["metadata"]["database"] == "old_set"
    restored["items"][0]["metadata"]["database"] = "postgres://host/db"
    with pytest.raises(ValueError, match="plain database name"):
        validate_bundle(restored)


def test_execution_evidence_includes_current_and_historical_presentations():
    """Keep display calls available to graders across the presentation migration."""
    from evals.utils import execution_evidence

    events = [
        {"name": "rank_units", "result": {"results": []}},
        {"name": "present_evidence", "result": {"presented": True}},
        {"name": "present_inline_data", "result": {"displayed": True}},
    ]
    result = {"metadata": {"tft_trace": {"events": events}}}
    evidence = execution_evidence(result)
    assert json.loads(evidence["presentation"]) == events[1:]
