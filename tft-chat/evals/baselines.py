"""Validate repository-authored regression definitions independently of UI exports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "baselines.json"


def authored_contract(bundle: dict[str, Any]) -> dict[str, Any]:
    """Project authored semantics while ignoring export transport and ordering.

    Args:
        bundle: An authored source or immutable native export.

    Returns:
        Routing and case contracts keyed by stable case identity.
    """
    cases = {}
    for item in bundle["items"]:
        identity = item["id"]
        if identity in cases:
            raise ValueError(f"Duplicate baseline case: {identity}")
        metadata = item["metadata"]
        cases[identity] = {
            "input": item["input"],
            "expected_output": item.get("expected_output"),
            "status": item.get("status", "ACTIVE"),
            "grading": {key: metadata.get(key) for key in (
                "case", "scoring", "quality_profile", "placeholder_checks",
                "deterministic_checks", "evidence_status", "quality_threshold",
            )},
        }
    return {
        "suite": {key: bundle["suite"].get(key) for key in (
            "name", "assistant", "family", "execution", "scoring", "max_turns",
        )},
        "cases": cases,
    }


def validate_baselines(manifest: Path = MANIFEST, snapshots: Path | None = None) -> dict[str, str]:
    """Resolve pinned snapshots and reject missing or drifted authored contracts.

    Args:
        manifest: Versioned baseline registry, beside the authored datasets.
        snapshots: Override for an isolated snapshot directory in tests.

    Returns:
        Suite names mapped to validated snapshot hashes.
    """
    from evals.langfuse.content import load_snapshot, validate_bundle
    from evals.langfuse.utils import validate_case_semantics

    registry = json.loads(manifest.read_text(encoding="utf-8"))
    if registry.get("schema_version") != 1 or not registry.get("suites"):
        raise ValueError("Invalid regression baseline manifest")
    resolved = {}
    for entry in registry["suites"]:
        name = entry["suite"]
        if name in resolved:
            raise ValueError(f"Duplicate baseline suite: {name}")
        bundle = load_snapshot(entry["snapshot"], snapshots or manifest.parent / "langfuse/snapshots")
        if bundle["suite"]["name"] != name:
            raise ValueError(f"Baseline suite identity mismatch: {name}")
        validate_case_semantics(bundle["suite"], bundle["items"])
        if entry.get("source"):
            source = (manifest.parent / entry["source"]).resolve()
            if not source.is_relative_to(manifest.parent.resolve()):
                raise ValueError(f"Baseline source escapes evaluation root: {name}")
            authored = validate_bundle(json.loads(source.read_text(encoding="utf-8")))
            expected, actual = authored_contract(authored), authored_contract(bundle)
            if expected != actual:
                cases = sorted(key for key in expected["cases"].keys() | actual["cases"].keys()
                               if expected["cases"].get(key) != actual["cases"].get(key))
                raise ValueError(f"Authored baseline drift in {name}: {cases or ['suite routing']}")
        resolved[name] = entry["snapshot"]
    return resolved


def main() -> None:
    """Print validated baseline hashes for explicit regression workflow selection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "snapshot"])
    parser.add_argument("suite", nargs="?")
    args = parser.parse_args()
    resolved = validate_baselines()
    if args.command == "snapshot":
        if args.suite not in resolved:
            parser.error(f"Unknown authored baseline: {args.suite}")
        print(resolved[args.suite])
    else:
        print(f"Validated {len(resolved)} authored regression baselines.")


if __name__ == "__main__":
    main()
