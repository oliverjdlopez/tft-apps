"""Safe discovery and editing of repository assistant specifications."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from domain.assistants import (
    ASSISTANT_SPECS_DIR,
    load_assistant_spec,
    reload_assistant_specs,
    resolve_assistant_tools,
)
from evals.config import load_eval_suites


REPO_ROOT = Path(__file__).resolve().parents[4]
EDITABLE_FILES = ("agent.json", "system.md", "task.md")


class DocumentConflictError(ValueError):
    """Raised when an editor tries to overwrite a newer spec revision."""


@dataclass(frozen=True)
class _SpecTarget:
    id: str
    assistant: str
    path: Path


def _document_id(assistant: str, filename: str) -> str:
    return hashlib.sha256(f"spec\0{assistant}\0{filename}".encode()).hexdigest()[:24]


def _revision(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _display_path(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()


def _targets() -> dict[str, _SpecTarget]:
    targets = []
    if not ASSISTANT_SPECS_DIR.is_dir():
        return {}
    for spec_dir in sorted(path for path in ASSISTANT_SPECS_DIR.iterdir() if path.is_dir()):
        if not (spec_dir / "system.md").is_file():
            continue
        spec = load_assistant_spec(spec_dir, root_dir=REPO_ROOT)
        for filename in EDITABLE_FILES:
            path = spec_dir / filename
            if path.is_file():
                targets.append(_SpecTarget(_document_id(spec.name, filename), spec.name, path))
    return {target.id: target for target in targets}


def _eval_suites_by_assistant() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for suite in load_eval_suites():
        result.setdefault(suite.assistant, []).append(suite.name)
    return result


def workspace() -> dict[str, Any]:
    """Return assistant metadata and allowlisted editable source files."""

    suites = _eval_suites_by_assistant()
    grouped: dict[str, dict[str, Any]] = {}
    for target in _targets().values():
        spec = load_assistant_spec(target.path.parent, root_dir=REPO_ROOT)
        item = grouped.setdefault(
            target.assistant,
            {
                "name": spec.name,
                "description": spec.description,
                "model": spec.model.value if spec.model else None,
                "tools": list(spec.tool_names),
                "tool_groups": list(spec.tool_group_keys),
                "handoffs": list(spec.handoff_names),
                "eval_suites": suites.get(spec.name, []),
                "sources": [],
            },
        )
        item["sources"].append(
            {
                "document_id": target.id,
                "label": target.path.name,
                "path": _display_path(target.path),
            }
        )
    return {"assistants": sorted(grouped.values(), key=lambda item: item["name"])}


def read_document(document_id: str) -> dict[str, Any]:
    target = _targets().get(document_id)
    if target is None:
        raise KeyError(document_id)
    content = target.path.read_text(encoding="utf-8")
    return {
        "id": target.id,
        "assistant": target.assistant,
        "label": target.path.name,
        "path": _display_path(target.path),
        "language": "json" if target.path.suffix == ".json" else "markdown",
        "content": content,
        "revision": _revision(content),
        "test_suites": _eval_suites_by_assistant().get(target.assistant, []),
    }


def _validate_specs(candidate_root: Path) -> None:
    specs = []
    for spec_dir in sorted(path for path in candidate_root.iterdir() if path.is_dir()):
        if (spec_dir / "system.md").is_file():
            specs.append(load_assistant_spec(spec_dir, root_dir=candidate_root.parent))
    names = [spec.name for spec in specs]
    if not names or len(names) != len(set(names)):
        raise ValueError("assistant names must be non-empty and unique")
    known = set(names)
    for spec in specs:
        missing = sorted(set(spec.handoff_names) - known)
        if missing:
            raise ValueError(f"unknown handoff assistant(s) in {spec.name}: {', '.join(missing)}")
        resolve_assistant_tools(spec)


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, path.stat().st_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def save_document(document_id: str, content: str, revision: str) -> dict[str, Any]:
    target = _targets().get(document_id)
    if target is None:
        raise KeyError(document_id)
    current = read_document(document_id)
    if revision != current["revision"]:
        raise DocumentConflictError("This file changed after it was opened. Reload it before saving.")
    if not content.strip():
        raise ValueError("assistant spec files cannot be empty")
    if target.path.name == "agent.json":
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("agent.json must contain a JSON object")

    with tempfile.TemporaryDirectory(prefix="tft-spec-") as temp_dir:
        candidate_root = Path(temp_dir) / ASSISTANT_SPECS_DIR.name
        shutil.copytree(ASSISTANT_SPECS_DIR, candidate_root)
        candidate = candidate_root / target.path.relative_to(ASSISTANT_SPECS_DIR)
        candidate.write_text(content, encoding="utf-8")
        _validate_specs(candidate_root)

    _atomic_write(target.path, content)
    reload_assistant_specs()
    return read_document(document_id)
