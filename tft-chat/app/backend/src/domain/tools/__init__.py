"""Direct registry for bounded TFT assistant tools."""

from __future__ import annotations

import inspect
import json
from copy import copy
from typing import Any

from agents import function_tool as _sdk_function_tool
from agents.tool_context import ToolContext

from common.serialization import model_jsonable
from domain.types import AssistantTool, AssistantToolGroup
from domain.tools.evidence import EvidenceStore, EVIDENCE_TOOL_GROUP, capture_evidence
from domain.tools.context import CONTEXT_TOOL_GROUP
from domain.tools.db_tools.cohort_tools import COHORT_TOOL_GROUP
from domain.tools.db_tools.deltas import DELTA_TOOL_GROUP
from domain.tools.db_tools.ranking_tools import RANKING_TOOL_GROUP
from domain.tools.rolldown import PROBABILITY_TOOL_GROUP
from .schemas import input_schema as _input_schema
from .schemas import output_schema as _output_schema


def _tool_name(tool: Any) -> str:
    return getattr(tool, "name", getattr(tool, "__name__", ""))


def _ensure_sdk_tool(tool: Any) -> Any:
    """Return an SDK tool whose model-visible output uses two decimals.

    Args:
        tool: Native SDK tool or Python callable to register.

    Returns:
        An SDK tool with the original metadata and a normalized invocation
        result. Database and calculator functions remain free to use their
        full internal precision until this model-facing boundary.
    """

    if hasattr(tool, "on_invoke_tool") and hasattr(tool, "params_json_schema"):
        sdk_tool = copy(tool)
    else:
        sdk_tool = _sdk_function_tool(tool, strict_mode=True)

    original_invoke = sdk_tool.on_invoke_tool

    async def invoke(ctx: ToolContext[Any], payload: str) -> Any:
        """Invoke the SDK tool and normalize its structured result."""

        output = await original_invoke(ctx, payload)
        references = capture_evidence(ctx.context, sdk_tool.name, output) if isinstance(ctx.context, EvidenceStore) else None
        result = model_jsonable(output)
        if references is not None:
            # SDK tools may return serialized JSON; evidence references accompany
            # the existing result without requiring the assistant to copy values.
            if isinstance(result, str):
                result = json.loads(result)
            result = {**result, "evidence": references}
        return result

    sdk_tool.on_invoke_tool = invoke
    return sdk_tool


# Standalone tools registered directly, without a group, for modules that
# expose one bounded tool and gain no clarity from wrapping it in a group.
# Each entry is an ``AssistantTool``; import it here the same way a group
# constant is imported above, e.g. ``_STANDALONE_TOOLS = (MY_TOOL,)``.
_STANDALONE_TOOLS: tuple[AssistantTool, ...] = ()

_TOOL_GROUPS = (
    COHORT_TOOL_GROUP,
    DELTA_TOOL_GROUP,
    RANKING_TOOL_GROUP,
    PROBABILITY_TOOL_GROUP,
    CONTEXT_TOOL_GROUP,
    EVIDENCE_TOOL_GROUP,
    *(standalone.as_group() for standalone in _STANDALONE_TOOLS),
)
_TOOL_GROUP_BY_KEY = {group.key: group for group in _TOOL_GROUPS}
_TOOL_GROUP_OF = {
    _tool_name(tool): group.key for group in _TOOL_GROUPS for tool in group.tools
}
_TOOL_FUNCTIONS = dict(
    sorted(
        (_tool_name(tool), _ensure_sdk_tool(tool))
        for group in _TOOL_GROUPS
        for tool in group.tools
    )
)


def get_tool(name: str) -> Any:
    """Return a registered SDK tool by name.

    Args:
        name: Registered tool name.

    Returns:
        The registered SDK tool.

    Raises:
        KeyError: If the tool is not registered.
    """
    try:
        return _TOOL_FUNCTIONS[name]
    except KeyError:
        raise KeyError(f"Unknown TFT tool: {name}") from None


def get_tool_group(key: str) -> AssistantToolGroup:
    """Return a registered tool group by key.

    Args:
        key: Registered tool-group key.

    Returns:
        The registered tool group.

    Raises:
        KeyError: If the tool group is not registered.
    """
    try:
        return _TOOL_GROUP_BY_KEY[key]
    except KeyError:
        raise KeyError(f"Unknown TFT tool group: {key}") from None


def list_tools() -> list[Any]:
    """Return all registered SDK tools sorted by name."""
    return [_TOOL_FUNCTIONS[name] for name in list_tool_names()]


def list_tool_groups() -> list[AssistantToolGroup]:
    """Return all registered tool groups in registration order."""
    return list(_TOOL_GROUPS)


def list_tool_names() -> list[str]:
    """Return every registered native TFT tool name."""
    return sorted(_TOOL_FUNCTIONS)


def list_tool_group_keys() -> list[str]:
    """Return every registered native TFT tool-group key."""
    return [group.key for group in _TOOL_GROUPS]


def get_tool_group_key(name: str) -> str:
    """Return the group key for a registered tool.

    Args:
        name: Registered tool name.

    Returns:
        The owning tool-group key.

    Raises:
        KeyError: If the tool is not registered.
    """
    try:
        return _TOOL_GROUP_OF[name]
    except KeyError:
        raise KeyError(f"Unknown TFT tool: {name}") from None


def get_tool_metadata(name: str) -> dict[str, Any]:
    """Return API-safe metadata for one registered tool.

    Args:
        name: Registered tool name.

    Returns:
        Tool name, description, and input/output schemas.
    """
    tool = get_tool(name)
    return {
        "name": name,
        "description": getattr(tool, "description", "")
        or inspect.getdoc(tool)
        or "",
        "input_schema": getattr(tool, "params_json_schema", None)
        or _input_schema(tool),
        "output_schema": _output_schema(tool) if callable(tool) else {},
    }


def list_tool_metadata(
    names: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return API-safe metadata for selected registered tools.

    Args:
        names: Optional tool names. All registered tools are returned when omitted.

    Returns:
        Tool metadata sorted by name when no explicit names are supplied.
    """
    selected = list_tool_names() if names is None else list(dict.fromkeys(names))
    return [get_tool_metadata(name) for name in selected]


def list_tool_group_metadata(
    names: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Return API-safe metadata for groups containing selected tools.

    Args:
        names: Optional tool names used to filter group contents.

    Returns:
        Group metadata in registration order.
    """
    selected_names = None if names is None else set(names)
    if selected_names is not None:
        for name in selected_names:
            get_tool(name)
    tools_by_name = {
        tool["name"]: tool for tool in list_tool_metadata(names)
    }
    groups: list[dict[str, Any]] = []
    for group in _TOOL_GROUPS:
        tools = [
            tools_by_name[_tool_name(tool)]
            for tool in group.tools
            if selected_names is None or _tool_name(tool) in selected_names
        ]
        if selected_names is not None and not tools:
            continue
        groups.append(
            {
                "key": group.key,
                "label": group.label,
                "description": group.description,
                "tools": tools,
            }
        )
    return groups


async def call_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
) -> Any:
    """Invoke one native TFT tool by name and return JSON-compatible data."""
    tool = get_tool(name)
    if callable(tool) and not hasattr(tool, "on_invoke_tool"):
        result = await tool(**(arguments or {}))
        return model_jsonable(result)
    payload = json.dumps(arguments or {})
    ctx = ToolContext(
        None,
        tool_name=name,
        tool_call_id=f"local-{name}",
        tool_arguments=payload,
    )
    result = await tool.on_invoke_tool(ctx, payload)
    return model_jsonable(result)


__all__ = [
    "AssistantTool",
    "AssistantToolGroup",
    "call_tool",
    "get_tool",
    "get_tool_group",
    "get_tool_group_key",
    "get_tool_metadata",
    "list_tool_group_keys",
    "list_tool_group_metadata",
    "list_tool_groups",
    "list_tool_metadata",
    "list_tool_names",
    "list_tools",
]
