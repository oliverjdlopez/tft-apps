"""Register a browser-owned Langfuse dataset from a small local definition."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .content import export_snapshot, load_catalog, load_snapshot, validate_bundle
from .contracts import DATASET_NAMES, dataset_schemas
from .prompts import repository_prompts
from .utils import default_config, validate_case_semantics


def register_dataset(
    *, name: str, dataset_name: str, assistant: str, description: str,
    items_path: Path | None, database: str | None, max_turns: int,
    snapshots: Path,
) -> dict[str, Any]:
    """Register one live assistant suite and optional initial cases for seeding.

    Args:
        name: Stable local suite identifier.
        dataset_name: Name shown in the Langfuse dataset list.
        assistant: Registered assistant to run for each case.
        description: Human-readable dataset purpose.
        items_path: Optional JSON array or object containing an ``items`` array.
        database: Optional suite-level evaluation database default.
        max_turns: Positive assistant turn limit.
        snapshots: Content-addressed snapshot catalog directory.

    Returns:
        Dataset name, snapshot ID, item count, and whether registration was new.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("Suite name must contain only letters, digits, underscores, or hyphens")
    if not dataset_name or dataset_name != dataset_name.strip():
        raise ValueError("Dataset name must be nonempty and have no surrounding whitespace")
    if type(max_turns) is not int or max_turns < 1:
        raise ValueError("max_turns must be a positive integer")
    if assistant not in repository_prompts():
        raise ValueError(f"Unknown assistant: {assistant}")
    entries = load_catalog(snapshots)
    if dataset_name in DATASET_NAMES.values():
        raise ValueError(f"Dataset name is already reserved: {dataset_name}")
    for entry in entries:
        existing = load_snapshot(entry["snapshot"], snapshots)
        if entry["name"] == name:
            if (not entry.get("managed_workflow") or existing.get("dataset_name") != dataset_name
                    or existing["suite"].get("assistant") != assistant):
                raise ValueError(f"Suite name is already registered: {name}")
            return {"dataset_name": dataset_name, "snapshot": entry["snapshot"],
                    "item_count": len(existing["items"]), "created": False}
        if existing.get("dataset_name") == dataset_name or f"chattft/{entry['name']}" == dataset_name:
            raise ValueError(f"Dataset name is already registered: {dataset_name}")

    suite = {"name": name, "assistant": assistant, "family": "assistant",
             "execution": "live", "database": database, "description": description,
             "max_turns": max_turns, "managed_workflow": True}
    source_items: list[Any] = []
    if items_path is not None:
        source = json.loads(items_path.read_text(encoding="utf-8"))
        source_items = source.get("items") if isinstance(source, dict) else source
        if not isinstance(source_items, list):
            raise ValueError("Initial items JSON must be an array or an object with an items array")
    items = []
    for source in source_items:
        if not isinstance(source, dict) or not isinstance(source.get("metadata", {}), dict):
            raise ValueError("Each initial item must be an object with object metadata")
        metadata = dict(source.get("metadata", {}))
        case = source.get("case") or metadata.get("case")
        if case is None and isinstance(source.get("id"), str):
            case = source["id"].rsplit("/", 1)[-1]
        if not isinstance(case, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", case):
            raise ValueError("Each initial item needs a case slug")
        case_id = f"{name}/{case}"
        if source.get("id", case_id) != case_id:
            raise ValueError(f"Case {case} has an ID outside suite {name}")
        if not isinstance(source.get("input"), str):
            raise ValueError(f"Case {case} input must be a string")
        metadata.update(case=case, case_id=case_id, suite=name)
        if metadata.get("scoring") != "none" and "quality_profile" not in metadata:
            metadata["quality_profile"] = "answer_quality"
        if metadata.get("scoring") != "none" and metadata.get("quality_profile") is None and not metadata.get("deterministic_checks"):
            raise ValueError(f"Case {case} needs a quality profile or deterministic checks")
        status = source.get("status", "ACTIVE")
        if status not in {"ACTIVE", "ARCHIVED"}:
            raise ValueError(f"Case {case} status must be ACTIVE or ARCHIVED")
        items.append({"id": case_id, "input": source["input"],
                      "expected_output": source.get("expected_output"),
                      "metadata": metadata, "status": status})
    bundle = {"schema_version": 3, "suite": suite, "dataset_name": dataset_name,
              "schemas": dataset_schemas(suite, version=3), "config": default_config(),
              "items": items, "prompts": {}}
    validate_bundle(bundle)
    validate_case_semantics(suite, items)
    snapshot = export_snapshot(bundle, snapshots)
    return {"dataset_name": dataset_name, "snapshot": snapshot,
            "item_count": len(items), "created": True}
