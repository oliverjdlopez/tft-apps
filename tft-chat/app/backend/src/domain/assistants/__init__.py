"""Public assistant registry, construction, and runtime API."""

from __future__ import annotations

from typing import Any


from domain.assistants.registry import AssistantRegistry, assistant_registry
from domain.assistants.runtime import prepare_resources
from domain.assistants.specs import (
    ASSISTANT_SPECS_DIR,
    SPECS_DIR,
    AssistantSpec,
    load_assistant_spec,
)
from domain.assistants.assistant import Assistant
from domain.assistants.models import AssistantInvocation
from domain.assistants.utils import configure_tools


_ASSISTANT_REGISTRY = assistant_registry


def assistant_spec(name: str) -> AssistantSpec:
    """Return a registered assistant specification.

    Args:
        name: Registered assistant name.

    Returns:
        The assistant specification.
    """
    return _ASSISTANT_REGISTRY.get_spec(name)


def assistant_handoff_names(name: str) -> list[str]:
    """Return direct handoff targets for an assistant.

    Args:
        name: Registered assistant name.

    Returns:
        Direct handoff assistant names in declaration order.
    """
    return _ASSISTANT_REGISTRY.get_handoff_names(name)


def resolve_assistant_tools(spec: AssistantSpec) -> list[Any]:
    """Resolve an assistant specification to registered SDK tools.

    Args:
        spec: Assistant specification declaring tool names and groups.

    Returns:
        Deduplicated SDK tools in declared group and name order.
    """
    configure_tools(_ASSISTANT_REGISTRY)
    return _ASSISTANT_REGISTRY.resolve_tools(spec)


def assistant_tools(name: str) -> list[Any]:
    """Return tools available directly to an assistant.

    Args:
        name: Registered assistant name.

    Returns:
        SDK tools resolved from the assistant specification.
    """
    configure_tools(_ASSISTANT_REGISTRY)
    return _ASSISTANT_REGISTRY.get_tools(name)


def assistant_tool_names(name: str) -> list[str]:
    """Return tool names available directly to an assistant.

    Args:
        name: Registered assistant name.

    Returns:
        Registered tool names in resolution order.
    """
    configure_tools(_ASSISTANT_REGISTRY)
    return _ASSISTANT_REGISTRY.list_tool_names(name)


def assistant_reachable_tool_names(name: str) -> list[str]:
    """Return tools callable by an assistant or its handoff targets.

    Args:
        name: Root registered assistant name.

    Returns:
        Deduplicated tool names in handoff traversal order.
    """
    configure_tools(_ASSISTANT_REGISTRY)
    return _ASSISTANT_REGISTRY.list_reachable_tool_names(name)


def list_assistants() -> list[str]:
    """Return registered assistant names sorted alphabetically."""
    return _ASSISTANT_REGISTRY.list_assistants()


def assistant_skill_names(name: str) -> list[str]:
    """Return discoverable skills the named assistant is allowed to read.

    Args:
        name: Registered assistant name.

    Returns:
        Skill names in repository discovery order.
    """
    from domain.providers.skills import DEFAULT_SKILL_PROVIDER

    available = [skill.name for skill in DEFAULT_SKILL_PROVIDER.discover()]
    return _ASSISTANT_REGISTRY.list_skill_names(name, available)


def reload_assistant_specs() -> None:
    """Reload assistant specifications from their source files."""
    _ASSISTANT_REGISTRY.reload()


__all__ = [
    "ASSISTANT_SPECS_DIR",
    "SPECS_DIR",
    "AssistantRegistry",
    "Assistant",
    "AssistantInvocation",
    "assistant_handoff_names",
    "assistant_reachable_tool_names",
    "assistant_spec",
    "assistant_skill_names",
    "assistant_tool_names",
    "assistant_tools",
    "list_assistants",
    "load_assistant_spec",
    "prepare_resources",
    "reload_assistant_specs",
    "resolve_assistant_tools",
]
