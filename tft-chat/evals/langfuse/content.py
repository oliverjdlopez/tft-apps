"""Seed, freeze, and export UI-authored Langfuse evaluation content."""
from __future__ import annotations

from copy import deepcopy
import fcntl
import json
from pathlib import Path
import re
from typing import Any

from domain.assistants.constants import AssistantName
from evals.utils import evaluation_database

from .utils import (atomic_write, canonical_json, catalog_revision,
                    check_assertion, content_hash, default_config, is_not_found,
                    resolved_prompt, utc_version, validate_frozen_config,
                    validate_case_semantics)


def validate_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Validate frozen definitions without requiring Langfuse or model credentials.

    Args:
        bundle: Self-contained dataset, prompts, and run configuration.

    Returns:
        An independent validated copy suitable for export or execution.
    """
    if not isinstance(bundle, dict):
        raise ValueError("Evaluation bundle must be an object")
    value = deepcopy(bundle)
    canonical_json(value)
    if value.get("schema_version") not in {1, 2, 3}:
        raise ValueError("Unsupported snapshot schema version")
    suite = value.get("suite")
    if not isinstance(suite, dict) or not isinstance(suite.get("name"), str):
        raise ValueError("Evaluation bundle requires suite metadata")
    if not isinstance(value.get("items"), list) or not isinstance(value.get("prompts"), dict):
        raise ValueError("Evaluation bundle requires items and prompts")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", suite["name"]):
        raise ValueError("Invalid suite name")
    if suite.get("family") not in {"assistant", "context_selection", "skill_selection"}:
        raise ValueError("Unknown suite family")
    if suite.get("execution") not in {"offline", "fixture", "live"}:
        raise ValueError("Unknown execution mode")
    if suite.get("scoring", "required") not in {"required", "none"}:
        raise ValueError("Unknown scoring mode")
    if suite.get("scoring") == "none" and (
            value["schema_version"] not in {2, 3} or suite.get("family") != "assistant"):
        raise ValueError("Unscored execution requires a natural assistant suite")
    evaluation_database(suite, {})
    if suite.get("max_turns") is not None and (type(suite["max_turns"]) is not int or suite["max_turns"] < 1):
        raise ValueError("max_turns must be a positive integer")
    from .contracts import reference_is_optional
    natural = value["schema_version"] in {2, 3}
    ids = set()
    for item in value["items"]:
        if not isinstance(item, dict):
            raise ValueError("Dataset items must be objects")
        if not isinstance(item.get("metadata"), dict) or not isinstance(item["metadata"].get("case"), str):
            raise ValueError("Dataset items require stable case metadata")
        if suite.get("scoring") == "none" or (value["schema_version"] == 3 and item["metadata"].get("scoring") == "none"):
            expected_output_is_valid = item.get("expected_output") is None
        else:
            expected_output_is_valid = (isinstance(item.get("expected_output"), (dict, str))
                or (item.get("expected_output") is None
                    and reference_is_optional(suite, item, version=value["schema_version"])))
        if not isinstance(item.get("input"), str if value["schema_version"] == 3 else dict) or not expected_output_is_valid:
            raise ValueError("Dataset input or expected output does not match the suite contract")
        evaluation_database(suite, item)
        if not isinstance(item.get("id"), str) or not item["id"].startswith(suite["name"] + "/") or item["id"] in ids:
            raise ValueError("Case IDs must be unique within their suite")
        ids.add(item["id"])
        if natural:
            from .contracts import validate_natural_item
            validate_natural_item(suite, item, version=value["schema_version"])
            continue
        if not isinstance(item["input"].get("input"), str):
            raise ValueError(f"Case {item['id']} input must be text")
        assertions = item["expected_output"].get("assertions")
        if not isinstance(assertions, list) or not assertions:
            raise ValueError(f"Case {item['id']} needs assertions")
        names = set()
        for assertion in assertions:
            if not isinstance(assertion, dict):
                raise ValueError("Each assertion must be an object")
            check_assertion(assertion)
            if assertion["name"] in names:
                raise ValueError(f"Duplicate assertion name: {assertion['name']}")
            names.add(assertion["name"])
        if suite["execution"] == "fixture":
            if not isinstance(item["input"].get("fixture", {}).get("output"), str):
                raise ValueError("Fixture cases require embedded output")
            if any(a["kind"] == "rubric" for a in assertions):
                raise ValueError("Fixture suites must remain credential-free")
    for prompt in value["prompts"].values():
        if not isinstance(prompt, dict):
            raise ValueError("Frozen prompt definitions must be objects")
        if not isinstance(prompt.get("text"), str) or not prompt["text"].strip() or type(prompt.get("version")) is not int:
            raise ValueError("Frozen prompts require text and a concrete version")
    config = value.setdefault("config", default_config())
    selected = config.get("cases", [])
    if set(selected) - ids:
        raise ValueError(f"Unknown case IDs: {sorted(set(selected) - ids)}")
    validate_frozen_config(config, suite)
    return value


def export_snapshot(bundle: dict[str, Any], root: Path, expected_revision: str | None = None) -> str:
    """Write immutable content and update the suite catalog with conflict detection.

    Args:
        bundle: Complete frozen evaluation definition.
        root: Reviewable snapshot directory.
        expected_revision: Catalog hash captured at request submission, if known.

    Returns:
        Content-addressed snapshot identifier.
    """
    value = validate_bundle(bundle)
    data = canonical_json(value)
    snapshot = content_hash(data)
    root.mkdir(parents=True, exist_ok=True)
    # A separate lock survives atomic catalog replacement and serializes writers.
    with (root / ".catalog.lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        revision = catalog_revision(root)
        if expected_revision is not None and revision != expected_revision:
            raise ValueError("Snapshot catalog changed; reload before exporting")
        entries = load_catalog(root)
        path = root / f"{snapshot}.json"
        if path.exists():
            if path.read_bytes().replace(b"\r\n", b"\n") != data:
                raise ValueError("Existing immutable snapshot was modified")
        else:
            atomic_write(path, data)
        entry = {**value["suite"], "snapshot": snapshot, "case_count": len(value["items"])}
        entries = [e for e in entries if e["name"] != entry["name"]] + [entry]
        if catalog_revision(root) != revision:
            raise ValueError("Snapshot catalog changed during export")
        atomic_write(root / "catalog.json", canonical_json({"schema_version": 1, "suites": sorted(entries, key=lambda e: e["name"])}))
    return snapshot


def load_snapshot(snapshot: str, root: Path) -> dict[str, Any]:
    """Load verified immutable snapshot content, rejecting paths and altered files."""
    if not re.fullmatch(r"[a-f0-9]{64}", snapshot):
        raise ValueError("Snapshot must be a SHA-256 identifier")
    data = (root / f"{snapshot}.json").read_bytes()
    if content_hash(data) != snapshot and content_hash(data.replace(b"\r\n", b"\n")) != snapshot:
        raise ValueError("Snapshot contents do not match its identifier")
    return validate_bundle(json.loads(data))


def load_catalog(root: Path) -> list[dict[str, Any]]:
    """Read the local suite index without connecting to Langfuse."""
    path = root / "catalog.json"
    if not path.exists():
        return []
    catalog = json.loads(path.read_text())
    if catalog.get("schema_version") != 1:
        raise ValueError("Unsupported catalog schema version")
    names = set()
    for entry in catalog["suites"]:
        if entry["name"] in names:
            raise ValueError("Duplicate suite in snapshot catalog")
        names.add(entry["name"])
        bundle = load_snapshot(entry["snapshot"], root)
        if any(entry.get(key) != item for key, item in bundle["suite"].items()):
            raise ValueError("Catalog metadata conflicts with immutable snapshot")
    return deepcopy(catalog["suites"])


def seed_content(client: Any, root: Path, *, natural: bool = False, include_fixtures: bool = False) -> dict[str, int]:
    """Create missing baseline datasets and prompts while preserving UI authoring.

    Args:
        client: Configured Langfuse SDK client.
        root: Committed snapshot catalog to import.

    Returns:
        Counts of newly created datasets, cases, and prompts.
    """
    from .contracts import ACTIVE_WORKFLOW_SUITES

    counts = {"datasets": 0, "items": 0, "prompts": 0}
    visited_prompts = set()
    if natural:
        from .prompts import repository_prompts
        # Current specs own the live prompt inventory. Historical snapshots must
        # neither resurrect retired prompts nor hide newly authored assistants.
        for prompt in repository_prompts().values():
            try:
                client.get_prompt(prompt["name"], label="latest", cache_ttl_seconds=0)
            except Exception as error:
                if not is_not_found(error):
                    raise
                client.create_prompt(name=prompt["name"], prompt=prompt["text"], type="text", labels=["baseline"])
                counts["prompts"] += 1
    for entry in load_catalog(root):
        if natural and not include_fixtures and entry["name"] not in ACTIVE_WORKFLOW_SUITES and not entry.get("managed_workflow"):
            continue
        if natural and entry['execution'] == 'fixture' and not include_fixtures:
            continue
        bundle = load_snapshot(entry["snapshot"], root)
        if natural:
            from .contracts import migrate_bundle
            import domain.assistants
            from domain.providers.skills import _discover_skills
            bundle = migrate_bundle(bundle, available_skills={skill.name for skill in _discover_skills()})
        for assistant_name, prompt in bundle["prompts"].items():
            if natural:
                continue
            if prompt["name"] in visited_prompts:
                continue
            visited_prompts.add(prompt["name"])
            try:
                client.get_prompt(prompt["name"], label="latest", cache_ttl_seconds=0)
            except Exception as error:
                if not is_not_found(error):
                    raise
                client.create_prompt(name=prompt["name"], prompt=prompt["text"], type="text", labels=["baseline"] if natural else ["production"])
                counts["prompts"] += 1
        dataset_name = (bundle.get("dataset_name") or f"chattft/{entry['name']}") if natural else f"chattft/{entry['name']}"
        try:
            dataset = client.get_dataset(dataset_name)
        except Exception as error:
            if not is_not_found(error):
                raise
            if natural:
                try:
                    client.get_dataset(f"chattft/{entry['name']}")
                except Exception as legacy_error:
                    if not is_not_found(legacy_error):
                        raise
                else:
                    raise ValueError('Existing legacy datasets require the explicit resumable migration first')
            client.create_dataset(name=dataset_name, description=bundle["suite"]["description"],
                                  metadata={"suite": bundle["suite"], "seed_snapshot": entry["snapshot"], "seed_complete": False})
            counts["datasets"] += 1
            dataset = client.get_dataset(dataset_name)
        metadata = dataset.metadata or {}
        if (natural and entry.get("managed_workflow") and metadata.get("seed_complete") is not False
                and metadata.get("contract_version") != 3):
            raise ValueError(f"Existing dataset {dataset_name} lacks the ChatTFT string-item contract")
        # Completed datasets belong to the UI, including intentional item deletions.
        if metadata.get("seed_complete") is not False:
            continue
        existing = {item.id for item in dataset.items}
        for item in bundle["items"]:
            remote_id = content_hash(f"chattft/{item['id']}".encode())
            if remote_id in existing:
                continue
            client.create_dataset_item(dataset_name=dataset_name, id=remote_id, input=item["input"],
                                       expected_output=item["expected_output"],
                                       metadata={**item["metadata"], "case_id": item["id"]},
                                       **({"status": item.get("status", "ACTIVE")} if natural else {}))
            counts["items"] += 1
        client.create_dataset(name=dataset_name, description=dataset.description,
                              metadata={**metadata, "seed_complete": True, **({"contract_version": bundle["schema_version"]} if natural else {})},
                              **({"input_schema": bundle["schemas"]["input"], "expected_output_schema": bundle["schemas"]["expected_output"]} if natural else {}))
    return counts


def fetch_bundle(client: Any, dataset_name: str, config: dict[str, Any], root: Path) -> dict[str, Any]:
    """Freeze one hosted dataset version and every prompt before queue submission.

    Args:
        client: Langfuse SDK client.
        dataset_name: Native dataset name selected by the UI.
        config: Validated experiment controls.
        root: Local catalog supplying suite routing defaults.

    Returns:
        Self-contained content plus hosted dataset/item linkage for SDK experiments.
    """
    from .contracts import DATASET_NAMES, PROFILE_DEFAULTS, migrate_bundle
    entries = {}
    for entry in load_catalog(root):
        entries[f"chattft/{entry['name']}"] = entry
        if entry.get("managed_workflow"):
            entries[load_snapshot(entry["snapshot"], root)["dataset_name"]] = entry
        else:
            entries[DATASET_NAMES[entry['name']]] = entry
    if dataset_name not in entries:
        raise ValueError(f"Unknown ChatTFT dataset: {dataset_name}")
    baseline = load_snapshot(entries[dataset_name]["snapshot"], root)
    if baseline["suite"]["name"] == AssistantName.ANALYZE_TRANSCRIPT and config.get("action", "run") != "export":
        raise ValueError("Archived analysis dataset has no executable workflow")
    version = utc_version(config.get("dataset_version"))
    dataset = client.get_dataset(dataset_name, version=version)
    contract_version = (dataset.metadata or {}).get("contract_version")
    natural = contract_version in {2, 3}
    value = migrate_bundle(baseline) if natural else deepcopy(baseline)
    if natural:
        value['schema_version'] = contract_version
        value['schemas'] = {'input': dataset.input_schema, 'expected_output': dataset.expected_output_schema}
    value.update(dataset_id=dataset.id, dataset_name=dataset_name, dataset_version=version.isoformat())
    value["items"] = []
    remote_items = dataset.items
    if natural:
        from .utils import configured_native_workspace
        from langfuse.api import DatasetItem
        native = configured_native_workspace()
        try:
            remote_items = [DatasetItem(id=item['id'], status=item['status'], input=item['input'],
                expected_output=item['expectedOutput'], metadata=item.get('metadata'),
                dataset_id=dataset.id, dataset_name=dataset_name,
                created_at=item['createdAt'], updated_at=item['updatedAt'], media_references=[],
                source_trace_id=item.get('sourceTraceId'), source_observation_id=item.get('sourceObservationId'))
                for item in native.items(dataset.id, version=version.isoformat())]
        finally:
            native.close()
    for item in remote_items:
        if not natural and str(item.status).upper().split(".")[-1] != "ACTIVE":
            continue
        metadata = deepcopy(item.metadata or {})
        if not isinstance(metadata, dict):
            raise ValueError("Dataset item metadata must be an object")
        case_id = metadata.get("case_id", f"{baseline['suite']['name']}/{item.id}")
        if not isinstance(case_id, str) or "/" not in case_id:
            raise ValueError("Dataset case_id must contain its suite and stable case name")
        metadata.setdefault("suite", baseline["suite"]["name"])
        metadata.setdefault("case", case_id.split("/", 1)[1])
        metadata.setdefault("case_id", case_id)
        if natural:
            profile = PROFILE_DEFAULTS.get(baseline['suite']['name'])
            if profile and metadata.get("scoring") != "none":
                metadata.setdefault('quality_profile', profile)
                metadata.setdefault('quality_threshold', .8)
            if baseline['suite']['family'] in {'context_selection', 'skill_selection'}:
                from .contracts import legacy_execution_item
                defaults = legacy_execution_item(baseline['items'][0])['expected_output']['assertions']
                metadata.setdefault('deterministic_checks', deepcopy(defaults))
        value["items"].append({"id": case_id, "remote_id": item.id, "input": deepcopy(item.input),
                               "expected_output": deepcopy(item.expected_output), "metadata": metadata,
                               **({"status": str(item.status).upper().split(".")[-1],
                                   "source_observation_id": item.source_observation_id,
                                   "source_trace_id": item.source_trace_id} if natural else {})})
    value["config"] = {**default_config(), **deepcopy(config), "dataset_version": version.isoformat()}
    prompt_inventory = baseline["prompts"]
    selected_suite = {**value["suite"], "assistant": value["config"].get("assistant") or value["suite"].get("assistant")}
    if natural:
        from .prompts import experiment_prompts
        prompt_inventory = experiment_prompts(selected_suite)
    value["prompts"] = {name: resolved_prompt(client, {"name": prompt["name"], "label": "baseline" if natural else "latest"})
                        for name, prompt in prompt_inventory.items()}
    for variant in value["config"]["variants"]:
        for assistant, reference in variant.get("prompts", {}).items():
            if assistant not in value["prompts"] or assistant == "judge":
                raise ValueError(f"Unknown assistant prompt target: {assistant}")
            variant["prompts"][assistant] = resolved_prompt(client, reference)
    if natural:
        from .contracts import migrate_item
        value['assertion_manifest'] = []
        for item in value['items']:
            original = item['metadata'].get('legacy_definition')
            if original:
                _, manifest = migrate_item(value['suite'], original)
                value['assertion_manifest'].extend(manifest)
        if value['suite'].get('scoring') == 'none':
            value.pop('grading', None)
        else:
            from .grading import freeze_grading
            from .utils import configured_workspace, load_grading_registry
            workspace = configured_workspace()
            try:
                value['grading'] = freeze_grading(workspace, load_grading_registry())
            finally:
                workspace.close()
    value = validate_bundle(value)
    validate_case_semantics(selected_suite, value["items"])
    return value
