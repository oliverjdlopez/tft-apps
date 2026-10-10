"""Run frozen ChatTFT evaluations through native Langfuse experiments."""
from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import partial
import os
from typing import Any
from uuid import uuid4

from evals.execution import execute_attempt, score_attempt
from evals.utils import execution_evidence, frozen_langfuse_prompt, experiment_item_report, public_experiment_url, prompt_reference_key


def run_item_task(*, item: Any, suite: dict, variant: dict, prompts: dict, client: Any = None,
                  native_prompt_references: dict | None = None, result_store: dict | None = None, **kwargs: Any) -> dict:
    """Execute frozen SDK or local items and expose usage and evidence in traces."""
    local = item if isinstance(item, dict) else {
        "input": item.input, "expected_output": item.expected_output, "metadata": item.metadata,
    }
    natural = isinstance(local["input"], str) or "input" not in local["input"]
    if natural and native_prompt_references is not None:
        # Portable replay may use source text without a matching destination
        # prompt version. Keep that lineage explicit instead of linking by number.
        prompts = {name: {**prompt, 'native_reference': native_prompt_references.get(prompt_reference_key(prompt))}
                   for name, prompt in prompts.items()}
        variant = {**variant, 'prompts': {
            name: {**prompt, 'native_reference': native_prompt_references.get(prompt_reference_key(prompt))}
            for name, prompt in variant.get('prompts', {}).items()}}
    result = execute_attempt(suite, local, variant, prompts)
    if result_store is not None:
        result_store[local["metadata"]["case_id"]] = result
    if client is not None:
        client.update_current_span(metadata={**result.get("metadata", {}),
                                            "prompt_versions": {key: {k: v for k, v in value.items() if k != "text"}
                                                                for key, value in {**prompts, **variant.get("prompts", {})}.items()}},
                                   level="ERROR" if result.get("error") else "DEFAULT",
                                   status_message=result.get("error"))
        if natural:
            from .contracts import PROFILE_DEFAULTS
            profile = (None if local.get("metadata", {}).get("scoring") == "none" else
                       local.get("metadata", {}).get("quality_profile", PROFILE_DEFAULTS.get(suite["name"])))
            client.update_current_span(metadata={
                "execution": suite["execution"],
                "execution_success": "false" if result.get("error") else "true",
                "quality_profile": profile or "none",
                "execution_evidence": execution_evidence(result),
            })
            return result.get("output")
        usage = result.get("token_usage", {})
        if usage:
            root_prompt = {**prompts, **variant.get("prompts", {})}.get(suite.get("assistant"))
            if root_prompt and native_prompt_references is not None:
                root_prompt = {**root_prompt, "native_reference": native_prompt_references.get(prompt_reference_key(root_prompt))}
            # SDK work happens in a killable child, so explicitly attach its usage.
            with client.start_as_current_observation(name="assistant-usage", as_type="generation",
                                                     model=result.get("metadata", {}).get("model"),
                                                     prompt=frozen_langfuse_prompt(root_prompt),
                                                     usage_details={"input": usage.get("prompt", 0),
                                                                    "output": usage.get("completion", 0),
                                                                    "total": usage.get("total", 0)}):
                pass
    return result


def evaluate_item(*, input: str | dict, output: dict, expected_output: str | dict | None, prompts: dict,
                  metadata: dict | None = None, result_store: dict | None = None, score_configs: dict | None = None, **kwargs: Any) -> list:
    """Publish authored scores with threshold and weight metadata through the SDK."""
    from langfuse import Evaluation
    if (metadata or {}).get("scoring") == "none":
        return []
    if result_store is not None:
        output = result_store[(metadata or {})["case_id"]]
    scores = score_attempt({"input": input, "expected_output": expected_output, "metadata": metadata or {}}, output, prompts)
    from .utils import native_score_name, deterministic_score_type
    checks = {check['name']: check for check in (metadata or {}).get('deterministic_checks', [])}
    return [Evaluation(name=native_score_name(score["name"]) if result_store is not None else score["name"], value=score["value"], comment=score["comment"],
                       data_type=(deterministic_score_type(checks[score["name"]]) if score["name"] in checks else
                                  "BOOLEAN" if score["name"] in {"execution_success", "contract_pass", "attempt_pass"} else "NUMERIC"),
                       config_id=(score_configs or {}).get(score["name"]),
                       metadata={"original_check_name": score["name"], "passed": score["passed"], "threshold": score["threshold"], "weight": score["weight"]})
            for score in scores]


def run_local_item(item: dict, *, suite: dict, variant: dict, prompts: dict) -> dict:
    """Run one credential-free fixture or selector and preserve its full scores."""
    result = execute_attempt(suite, item, variant, prompts)
    from .utils import artifact_execution_fields
    return {"id": item["id"], "result": result, "result_is_execution_wrapper": True,
            "scores": score_attempt(item, result, prompts),
            **artifact_execution_fields(result)}


def run_bundle(bundle: dict, client: Any = None, *, group_id: str | None = None) -> dict:
    """Execute frozen variants/repetitions with hosted dataset linkage when online.

    Args:
        bundle: Validated and exported immutable definition bundle.
        client: Langfuse client, or None for credential-free local execution.
        group_id: Durable job/comparison identifier shared by all experiments.

    Returns:
        Explicit overall pass state and per-experiment result references.
    """
    from evals.langfuse.content import validate_bundle
    bundle = validate_bundle(bundle)
    natural = bundle["schema_version"] in {2, 3}
    unscored = natural and bundle["suite"].get("scoring") == "none"
    started = datetime.now(timezone.utc)
    config = bundle["config"]
    if config.get("action") == "export":
        raise ValueError("Export-only bundles cannot execute evaluations")
    if natural and not unscored and client is not None and not bundle.get('grading'):
        raise ValueError('Online natural experiments require frozen native grading definitions')
    if client is not None:
        bundle = bind_dataset_identity(bundle, client)
        if natural and bundle.get('grading'):
            from .grading import verify_grading
            from .utils import configured_workspace
            workspace = configured_workspace()
            try:
                verify_grading(workspace, bundle['grading'])
            finally:
                workspace.close()
    group_id = group_id or str(uuid4())
    selected = set(config.get("cases", []))
    items = [item for item in bundle["items"] if item.get("status", "ACTIVE") == "ACTIVE" and (not selected or item["id"] in selected)]
    if natural and not items:
        raise ValueError('No active cases selected; archived and empty datasets cannot pass an experiment')
    for item in items:
        item["metadata"].setdefault("case_id", item["id"])
    suite = dict(bundle["suite"])
    if bundle.get('execution'):
        suite['captured_graphs'] = bundle['execution']['graphs']
        suite['workspace_lineage'] = bundle['execution'].get('lineage')
    if config.get("assistant") is not None:
        suite["assistant"] = config["assistant"]
    if suite["family"] in {"context_selection", "skill_selection"}:
        suite["execution"] = "live" if config.get("selection_live") else "offline"
    if config.get("data_snapshot_label"):
        suite["dataset"] = config["data_snapshot_label"]
    if client is None and (suite.get("execution") == "live" or any(
            assertion["kind"] == "rubric" for item in items for assertion in (item["expected_output"].get("assertions", []) if isinstance(item["expected_output"], dict) else []))):
        raise ValueError("Live and rubric evaluations require a Langfuse client; local runs are credential-free")
    if natural and client is None and any(item.get("metadata", {}).get("quality_profile") for item in items):
        raise ValueError("Native quality grading requires an online workspace")
    cap = int(os.environ.get("LANGFUSE_MAX_CONCURRENCY", "4"))
    concurrency = min(config.get("concurrency", 4), cap)
    experiments = []
    for variant in config["variants"]:
        variant_prompts = bundle.get('execution', {}).get('prompts', {}).get(variant['name'], bundle['prompts'])
        for repetition in range(1, config["repetitions"] + 1):
            name = (f"{variant['name']} · {started.isoformat(timespec='microseconds')} · r{repetition}" if natural
                    else f"{suite['name']}/{variant['name']}/{group_id}/r{repetition}")
            if not items:
                experiments.append({"name": name, "passed": True, "empty": True, "items": []})
                continue
            if client is None:
                task = partial(run_local_item, suite=suite, variant=variant, prompts=variant_prompts)
                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    results = list(pool.map(task, items))
                experiments.append({"name": name, "passed": all(row["scores"][-1]["passed"] for row in results), "items": results})
                continue
            from langfuse.api import DatasetItem
            version = datetime.fromisoformat(bundle["dataset_version"].replace("Z", "+00:00"))
            # Dictionaries are treated as local datasets by the SDK. Reconstruct
            # hosted objects from frozen content instead of refetching UI edits.
            data = [DatasetItem(id=item["remote_id"], status="ACTIVE", input=item["input"],
                                expected_output=item["expected_output"], metadata={key: value for key, value in item["metadata"].items()
                                                                                 if key != "legacy_definition"},
                                dataset_id=bundle["dataset_id"], dataset_name=bundle["dataset_name"],
                                created_at=version, updated_at=version, media_references=[]) for item in items]
            result_store = {}
            evaluators = [] if unscored else [partial(
                evaluate_item, prompts=variant_prompts, result_store=result_store if natural else None,
                score_configs=bundle.get("grading", {}).get("score_configs", {}),
            )]
            result = client.run_experiment(
                name=name, run_name=name, data=data, _dataset_version=version,
                task=partial(run_item_task, suite=suite, variant=variant, prompts=variant_prompts, client=client,
                             native_prompt_references=bundle.get("native_prompt_references"), result_store=result_store),
                evaluators=evaluators,
                max_concurrency=concurrency,
                metadata={"comparison_group": group_id, "variant": variant["name"], "repetition": str(repetition),
                          "workspace_lineage": bundle.get('execution', {}).get('lineage', {}),
                          "assistant_graph_hash": bundle.get('execution', {}).get('graphs', {}).get(variant['name'], {}).get('hash'),
                          "snapshot": bundle.get("snapshot_id") or config.get("snapshot") or "",
                          **{key: str(value) for key, value in bundle.get("provenance", {}).items()}, "dataset_version": bundle["dataset_version"],
                          "data_snapshot_label": config.get("data_snapshot_label") or ""},
            )
            completed = bool(result.dataset_run_id) and len(result.item_results) == len(items)
            passed = completed and (
                all(item["id"] in result_store and not result_store[item["id"]].get("error")
                    for item in items)
                if unscored
                else all(any(score.name == "attempt_pass" and score.value == 1 for score in row.evaluations)
                         for row in result.item_results)
            )
            reports = [experiment_item_report(row) for row in result.item_results]
            if natural:
                from .contracts import PROFILE_DEFAULTS
                by_id = {item["id"]: item for item in items}
                for row in reports:
                    metadata = by_id[row["id"]]["metadata"]
                    if unscored or metadata.get("scoring") == "none":
                        row.update(execution_success=not result_store.get(row["id"], {}).get("error"),
                                   scoring="none", quality_profile=None, contract_pass=True)
                    else:
                        row.update(quality_profile=metadata.get("quality_profile", PROFILE_DEFAULTS.get(suite["name"])),
                                   quality_threshold=metadata.get("quality_threshold", .8),
                                   execution_success=any(s["name"] == "execution_success" and s["value"] == 1 for s in row["scores"]),
                                   contract_pass=any(s["name"] == "contract_pass" and s["value"] == 1 for s in row["scores"]))
            returned = {row["remote_id"] for row in reports}
            # The SDK may omit a failed task; retain that failure in CI artifacts.
            reports.extend({"id": item["id"], "remote_id": item["remote_id"], "scores": [],
                            "result": {"error": "SDK did not return an experiment item result"},
                            "result_is_execution_wrapper": True}
                           for item in items if item["remote_id"] not in returned)
            from .utils import artifact_execution_fields
            for row in reports:
                row.setdefault("result_is_execution_wrapper", not natural)
                captured = result_store.get(row["id"])
                if captured is not None:
                    row.update(artifact_execution_fields(captured))
            experiments.append({"name": name, "passed": passed, "dataset_run_id": result.dataset_run_id,
                                "url": public_experiment_url(result.dataset_run_url), "item_count": len(result.item_results), "items": reports})
    if client is not None:
        client.flush()
    if natural and not unscored and client is not None:
        import time
        return {"passed": False, "state": "awaiting_scores", "started_at": started.isoformat(),
                "grading_deadline": time.time() + 600, "group_id": group_id, "experiments": experiments,
                **({'source_dataset': bundle['source_dataset'], 'effective_grading': bundle['grading']}
                   if bundle.get('source_grading') else {})}
    return {"passed": all(row["passed"] for row in experiments), "group_id": group_id, "experiments": experiments}


def bind_dataset_identity(bundle: dict, client: Any) -> dict:
    """Verify destination identities and rebind portable snapshots without replacing inputs.

    Args:
        bundle: Frozen local snapshot, optionally already carrying hosted IDs.
        client: SDK client for read-only dataset identity discovery.

    Returns:
        Independent execution copy with native dataset and case associations.
    """
    frozen = deepcopy(bundle)
    name = frozen.get("dataset_name") or f"chattft/{frozen['suite']['name']}"
    try:
        dataset = client.get_dataset(name)
    except Exception as error:
        from .contracts import DATASET_NAMES
        from .utils import is_not_found
        replacement = DATASET_NAMES.get(frozen['suite']['name'])
        if not is_not_found(error) or not replacement or replacement == name:
            raise
        name = replacement
        dataset = client.get_dataset(name)
    complete = all(frozen.get(key) for key in ("dataset_id", "dataset_name", "dataset_version")) and all(
        item.get("remote_id") for item in frozen["items"])
    if complete and frozen["dataset_id"] == dataset.id:
        # Historical replay on the same platform keeps its exact version, even
        # when a case has subsequently been edited, archived, or deleted.
        frozen['dataset_name'] = name
        return frozen
    relocated = bool(frozen.get("dataset_id") and frozen["dataset_id"] != dataset.id)
    if relocated:
        frozen["source_dataset"] = {key: frozen.get(key) for key in ("dataset_id", "dataset_name", "dataset_version")}
        if frozen.get('grading'):
            from .grading import rebind_grading
            from .utils import configured_workspace, load_grading_registry
            workspace = configured_workspace()
            try:
                frozen['source_grading'] = frozen['grading']
                frozen['grading'] = rebind_grading(workspace, frozen['grading'], load_grading_registry())
            finally:
                workspace.close()
    identities = {}
    for item in dataset.items:
        metadata = item.metadata or {}
        case_id = metadata.get("case_id") or f"{metadata.get('suite', frozen['suite']['name'])}/{metadata.get('case', '')}"
        if case_id in identities:
            raise ValueError(f"Ambiguous hosted identity for {case_id}")
        identities[case_id] = item.id
    for item in frozen["items"]:
        if item["id"] not in identities:
            raise ValueError(f"Hosted dataset is missing frozen case {item['id']}; seed its identity first")
        item["remote_id"] = identities[item["id"]]
    frozen["dataset_id"] = dataset.id
    frozen["dataset_name"] = name
    version = getattr(dataset, "version", None) or datetime.now(timezone.utc)
    if relocated or not frozen.get("dataset_version"):
        frozen["dataset_version"] = version.isoformat()
    frozen["native_prompt_references"] = bind_prompt_references(frozen, client)
    return frozen



def bind_prompt_references(bundle: dict, client: Any) -> dict:
    """Link relocated frozen prompts only to destination versions with matching text.

    Args:
        bundle: Frozen source prompts and variant candidates.
        client: Destination SDK client used only for prompt identity reads.

    Returns:
        Content-keyed native identities, with None for absent or mismatched text.
    """
    from evals.langfuse.utils import resolved_prompt, is_not_found
    prompts = list(bundle["prompts"].values())
    prompts.extend(prompt for variant in bundle["config"]["variants"] for prompt in variant.get("prompts", {}).values())
    destination = {}
    references = {}
    for source in prompts:
        if source["name"] not in destination:
            try:
                destination[source["name"]] = resolved_prompt(client, {"name": source["name"], "label": "latest"})
            except Exception as error:
                if not isinstance(error, ValueError) and not is_not_found(error):
                    raise
                destination[source["name"]] = None
        target = destination[source["name"]]
        references[prompt_reference_key(source)] = (
            {"name": target["name"], "version": target["version"]}
            if target and target["text"] == source["text"] else None)
    return references
