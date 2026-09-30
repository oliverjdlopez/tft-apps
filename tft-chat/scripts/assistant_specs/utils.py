"""Validation and dependency inspection for assistant lifecycle commands."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re


# ======================================================================
# main: repository spec lifecycle
# Validate source identities before constructing writable paths.
# Dependency checks deliberately favor reporting a caller over deleting it.
# ======================================================================


def validate_name(name: str) -> str:
    """Validate a single directory name supplied to the management CLI."""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name) or name in {"readme", "agents", "judge"}:
        raise ValueError("Use a lowercase assistant name with letters, digits, and underscores.")
    return name


def spec_inventory(root: Path) -> dict:
    """Load directory specs strictly so malformed sources cannot masquerade as retired."""
    from domain.assistants.specs import load_assistant_spec

    result = {}
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not (directory / "system.md").exists():
            continue
        if directory.is_symlink() or any(path.is_symlink() for path in directory.rglob("*")):
            raise ValueError(f"Spec contains a symbolic link: {directory.name}")
        spec = load_assistant_spec(directory, root_dir=root.parent)
        if spec.name.casefold() in {name.casefold() for name in result}:
            raise ValueError(f"Duplicate assistant name: {spec.name}")
        result[spec.name] = (directory, spec)
    # Legacy single-file specs are supported by discovery but are not writable
    # through this directory-based command. Include them when checking identity.
    for path in sorted(root.glob("*.md")):
        if path.name.lower() in {"readme.md", "agents.md"}:
            continue
        spec = load_assistant_spec(path, root_dir=root.parent)
        if spec.name in result:
            raise ValueError(f"Duplicate assistant name: {spec.name}")
        result[spec.name] = (path, spec)
    return result


def removal_dependencies(name: str, specs: dict, repo: Path) -> list[str]:
    """Find handoffs, executable Python references, and active eval dependencies.

    Args:
        name: Assistant being considered for removal.
        specs: Strict inventory of current source definitions.
        repo: Checkout root containing runtime callers and snapshot catalog.

    Returns:
        Concrete blockers to resolve before applying removal.
    """
    blockers = [f"handoff from {other}" for other, (_, spec) in specs.items()
                if other != name and name in spec.handoff_names]
    for source_root in (repo / "app/backend", repo / "scripts"):
        for path in sorted(source_root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            lines = {node.lineno for node in ast.walk(tree)
                     if isinstance(node, ast.Constant) and node.value == name}
            blockers.extend(f"source reference {path.relative_to(repo)}:{line}" for line in sorted(lines))
    catalog = repo / "evals/langfuse/snapshots/catalog.json"
    if catalog.exists():
        # Read raw metadata here: retiring a broken spec must still provide an
        # actionable report even when registry-dependent catalog validation fails.
        for entry in json.loads(catalog.read_text())["suites"]:
            if entry.get("assistant") == name:
                blockers.append(f"eval suite {entry['name']} targets this assistant")
            bundle = json.loads((catalog.parent / f"{entry['snapshot']}.json").read_text())
            for variant in bundle.get("config", {}).get("variants", []):
                if name in variant.get("prompts", {}):
                    blockers.append(f"eval suite {entry['name']} has a candidate for this assistant")
            # Frozen prompt inventories are history, but active authored checks
            # that demand an assistant still need deliberate migration.
            for item in bundle.get("items", []):
                if item.get("status") == "ARCHIVED":
                    continue
                checks = item.get("metadata", {}).get("deterministic_checks", [])
                expected = item.get("expected_output")
                if isinstance(expected, dict):
                    checks += expected.get("assertions", [])
                if re.search(r'"' + re.escape(name) + r'"', json.dumps(checks)):
                    blockers.append(f"eval case {item['id']} checks this assistant")
    return sorted(set(blockers))
