"""Load assistant specifications and resolve their declared tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.parsers import first_markdown_heading
from domain.assistants.constants import ROOT_DIR
from domain.assistants.models import AssistantSpec


# -----------------------------------------------------------------------------
# Registry construction
#
# Resolve declared tool access once for each registered definition.
# -----------------------------------------------------------------------------

def resolve_tools(spec: AssistantSpec) -> list[Any]:
    """Resolve an assistant specification to registered SDK tools.

    Args:
        spec: Assistant specification declaring tool names and groups.

    Returns:
        Deduplicated SDK tools in declared group and name order.

    Raises:
        KeyError: If a declared tool or tool group is not registered.
    """
    # Load the tool catalogue only when resolving a specification.
    from domain.tools import get_tool, get_tool_group, list_tools, tool_name

    if spec.include_all_tools:
        return list_tools()

    resolved: list[Any] = []
    seen: set[str] = set()
    for group_key in spec.tool_group_keys:
        for grouped_tool in get_tool_group(group_key).list_tools():
            name = tool_name(grouped_tool)
            if name not in seen:
                resolved.append(get_tool(name))
                seen.add(name)
    for name in spec.tool_names:
        tool = get_tool(name)
        if name not in seen:
            resolved.append(tool)
            seen.add(name)
    return resolved


# -----------------------------------------------------------------------------
# Assistant specification loading
#
# Translate repository files into validated runtime definitions.
# -----------------------------------------------------------------------------

def resource_spec_fields(resources: object) -> dict[str, Any]:
    """Translate resource configuration into AssistantSpec permission fields.

    Args:
        resources: The agent.json resources object shared by both spec loaders.

    Returns:
        Model fields preserving omitted versus explicitly empty allowlists.

    Raises:
        ValueError: If resource objects or keys are malformed. AssistantSpec
            validates the resulting boolean and allowlist values.
    """
    if not isinstance(resources, dict):
        raise ValueError("resources must be an object")
    unsupported = set(resources) - {"context", "skills", "playbooks"}
    if unsupported:
        raise ValueError(f"unsupported resources keys: {', '.join(sorted(unsupported))}")
    context = resources.get("context", {})
    if not isinstance(context, dict):
        raise ValueError("resources.context must be an object")
    unsupported = set(context) - {"repository"}
    if unsupported:
        raise ValueError(f"unsupported resources.context keys: {', '.join(sorted(unsupported))}")
    return {
        "repository_context": context.get("repository", False),
        "skill_names": resources.get("skills"),
        "playbook_names": resources.get("playbooks"),
    }


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
    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {}
    )
    if not isinstance(config, dict):
        raise ValueError("agent.json must contain a JSON object")
    tools = config.pop("tools", [])
    if not isinstance(tools, dict):
        tools = {"names": tools}
    if {"context", "skills", "playbooks"} & config.keys():
        raise ValueError("context, skills, and playbooks must be nested under resources")
    resource_fields = resource_spec_fields(config.pop("resources", {}))
    name = config.pop("name", spec_dir.name)
    if name != spec_dir.name:
        raise ValueError(
            f"assistant name {name!r} must match its directory {spec_dir.name!r}"
        )
    description = config.pop(
        "description", first_markdown_heading(system_prompt) or name
    )
    task_path = spec_dir / "task.md"
    return AssistantSpec(
        name=name,
        description=description,
        handoff_description=config.pop("handoff_description", description),
        system_prompt=system_prompt,
        task_prompt=(
            task_path.read_text(encoding="utf-8").strip() if task_path.exists() else ""
        ),
        path=str(system_path.relative_to(root_dir)),
        include_all_tools=tools.get("include_all", False),
        tool_group_keys=tools.get("groups", ()),
        tool_names=tools.get("names", ()),
        handoff_names=config.pop("handoffs", ()),
        **resource_fields,
        **config,
    )
