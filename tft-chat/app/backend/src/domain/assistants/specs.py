"""Load repository files into runtime assistant definitions."""

from __future__ import annotations

import json
from pathlib import Path

from common.discoverers import discover_files
from common.parsers import first_markdown_heading
from common.paths import find_repo_root
from domain.assistants.models import AssistantSpec


ROOT_DIR = find_repo_root()
SPECS_DIR = ROOT_DIR / "app" / "backend" / "src" / "domain" / "assistant_specs"
ASSISTANT_SPECS_DIR = SPECS_DIR


def load_assistant_spec(path: Path, *, root_dir: Path = ROOT_DIR) -> AssistantSpec:
    """Read one assistant directory and translate its JSON fields into the model.

    Args:
        path: Assistant directory or its ``system.md`` path.
        root_dir: Root used to retain a repository-relative source path.

    Returns:
        An immutable definition validated by AssistantSpec.
    """
    system_path = path / "system.md" if path.is_dir() else path
    if system_path.name != "system.md":
        raise ValueError("assistant specifications require a system.md file")
    spec_dir = system_path.parent
    system_prompt = system_path.read_text(encoding="utf-8").strip()
    config_path = spec_dir / "agent.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError("agent.json must contain a JSON object")
    tools = config.pop("tools", [])
    if not isinstance(tools, dict):
        tools = {"names": tools}
    context = config.pop("context", {})
    if not isinstance(context, dict):
        raise ValueError("context must be an object")
    name = config.pop("name", spec_dir.name)
    if name != spec_dir.name:
        raise ValueError(f"assistant name {name!r} must match its directory {spec_dir.name!r}")
    description = config.pop("description", first_markdown_heading(system_prompt) or name)
    task_path = spec_dir / "task.md"
    return AssistantSpec(
        name=name,
        description=description,
        handoff_description=config.pop("handoff_description", description),
        system_prompt=system_prompt,
        task_prompt=task_path.read_text(encoding="utf-8").strip() if task_path.exists() else "",
        path=str(system_path.relative_to(root_dir)),
        include_all_tools=tools.get("include_all", False),
        tool_group_keys=tools.get("groups", ()),
        tool_names=tools.get("names", ()),
        handoff_names=config.pop("handoffs", ()),
        repository_context=context.get("repository", False),
        skill_names=config.pop("skills", None),
        playbook_names=config.pop("playbooks", None),
        **config,
    )


def discover_assistants_specs() -> list[AssistantSpec]:
    """Load the repository's assistant directories; the registry checks the graph."""
    return [
        load_assistant_spec(path)
        for path in discover_files(ASSISTANT_SPECS_DIR, ["*/system.md"])
    ]
