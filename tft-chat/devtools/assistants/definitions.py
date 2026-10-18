"""Compatibility loading for authored drafts and historical assistant sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from common.parsers import first_markdown_heading, parse_frontmatter, parse_string_list
from common.paths import find_repo_root
from domain.assistants.models import AssistantSpec
from domain.assistants.utils import resource_spec_fields


ROOT_DIR = find_repo_root()
AGENT_CONFIG_FILE = "agent.json"
TASK_PROMPT_FILE = "task.md"


def _read_agent_config(spec_dir: Path) -> dict[str, Any]:
    """Read an optional historical configuration object."""
    config_path = spec_dir / AGENT_CONFIG_FILE
    if not config_path.exists():
        return {}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    return config


def _metadata_list(metadata: dict[str, str], *keys: str) -> tuple[str, ...]:
    for key in keys:
        if key in metadata:
            return parse_string_list(metadata[key], field=key)
    return ()


def _metadata_bool(metadata: dict[str, str], key: str) -> bool:
    value = metadata.get(key)
    return bool(
        value is not None
        and value.strip().lower() in {"1", "true", "yes", "on", "all"}
    )


def _read_tool_access(
    config: dict[str, Any], metadata: dict[str, str],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Normalize historical tool fields into the runtime contract."""
    raw_tools = config.get("tools")
    if isinstance(raw_tools, bool):
        return raw_tools, (), ()
    if isinstance(raw_tools, str | list | tuple):
        return False, (), parse_string_list(raw_tools, field="tools")
    if raw_tools is not None and not isinstance(raw_tools, dict):
        raise ValueError("tools must be a boolean, string, list, or object")
    tool_config = raw_tools or {}
    include_all = bool(
        tool_config.get("include_all")
        or tool_config.get("all")
        or config.get("include_all_tools")
        or _metadata_bool(metadata, "include_all_tools")
    )
    groups = parse_string_list(
        tool_config.get("groups", config.get("tool_groups")),
        field="tools.groups",
    ) or _metadata_list(metadata, "tool_groups", "tool_group_keys")
    names = parse_string_list(
        tool_config.get("names", tool_config.get("allow", config.get("tool_names"))),
        field="tools.names",
    ) or _metadata_list(metadata, "tool_names", "tools")
    return include_all, groups, names


def _read_handoffs(
    config: dict[str, Any], metadata: dict[str, str],
) -> tuple[str, ...]:
    """Normalize historical handoff fields into assistant names."""
    raw_handoffs = config.get("handoffs", config.get("handoff_names"))
    if isinstance(raw_handoffs, dict):
        raw_handoffs = raw_handoffs.get("agents", raw_handoffs.get("names"))
    return parse_string_list(raw_handoffs, field="handoffs") or _metadata_list(
        metadata, "handoffs", "handoff_names",
    )


def load_development_spec(
    path: Path, *, root_dir: Path = ROOT_DIR,
) -> AssistantSpec:
    """Load a current or historical definition for development tooling.

    The application loader deliberately excludes these aliases. This adapter is
    retained for old workspace revisions, captures, and migration commands.
    """
    system_path = path / "system.md" if path.is_dir() else path
    spec_dir = system_path.parent
    config = _read_agent_config(spec_dir)
    parsed = parse_frontmatter(system_path.read_text(encoding="utf-8"))
    metadata = parsed.metadata
    body = parsed.body.strip()
    name = str(
        config.get("name")
        or metadata.get("name")
        or (system_path.parent.name if system_path.stem == "system" else system_path.stem)
    )
    configured_system = config.get("system_prompt") or metadata.get("system_prompt")
    system_prompt = str(configured_system).strip() if configured_system else body
    task_path = spec_dir / TASK_PROMPT_FILE
    if task_path.exists():
        task_prompt = task_path.read_text(encoding="utf-8").strip()
    elif configured_system:
        task_prompt = body
    else:
        task_prompt = str(
            config.get("task_prompt") or metadata.get("task_prompt") or ""
        ).strip()
    description = str(
        config.get("description")
        or metadata.get("description")
        or first_markdown_heading(system_prompt)
        or name
    )
    handoff_description = str(
        config.get("handoff_description")
        or metadata.get("handoff_description")
        or description
    )
    include_all_tools, tool_group_keys, tool_names = _read_tool_access(config, metadata)
    # Historical drafts retain their flat fields; current definitions have one
    # resource object. Reject mixed forms rather than silently changing access.
    legacy_resources = {key: config[key] for key in ("context", "skills", "playbooks") if key in config}
    if "resources" in config and legacy_resources:
        raise ValueError("context, skills, and playbooks must be nested under resources")
    resource_fields = resource_spec_fields(config.get("resources", legacy_resources))
    values: dict[str, Any] = {
        "name": name,
        "description": description,
        "handoff_description": handoff_description,
        "system_prompt": system_prompt,
        "task_prompt": task_prompt,
        "path": str(system_path.relative_to(root_dir)),
        "include_all_tools": include_all_tools,
        "tool_group_keys": tool_group_keys,
        "tool_names": tool_names,
        "handoff_names": _read_handoffs(config, metadata),
        **resource_fields,
    }
    model = config.get("model") or metadata.get("model")
    reasoning = config.get("reasoning") or metadata.get("reasoning")
    if model:
        values["model"] = str(model).strip()
    if reasoning:
        values["reasoning"] = str(reasoning).strip()
    return AssistantSpec(**values)


__all__ = ["load_development_spec"]
