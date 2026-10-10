"""Public assistant registry, construction, and runtime API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from domain.assistants.agent import AssistantAgent
from domain.assistants.assistants import (
    build_assistant as _build_assistant,
    build_assistant_instructions,
    render_input as _render_input,
)
from domain.assistants.registry import AssistantRegistry, assistant_registry
from domain.assistants.runtime import prepare_resources
from domain.assistants.specs import (
    ASSISTANT_SPECS_DIR,
    SPECS_DIR,
    AssistantSpec,
    load_assistant_spec,
)
from domain.assistants.token_logging import log_agent_graph
from domain.providers.models import ContextProvider, SkillProvider


_ASSISTANT_REGISTRY = assistant_registry


def _configure_tools() -> None:
    """Connect the assistant registry to the public tool registry API."""
    from domain.tools import get_tool, get_tool_group, list_tools

    _ASSISTANT_REGISTRY.configure_tools(
        get_tool=get_tool,
        get_tool_group=get_tool_group,
        list_tools=list_tools,
    )


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
    _configure_tools()
    return _ASSISTANT_REGISTRY.resolve_tools(spec)


def assistant_tools(name: str) -> list[Any]:
    """Return tools available directly to an assistant.

    Args:
        name: Registered assistant name.

    Returns:
        SDK tools resolved from the assistant specification.
    """
    _configure_tools()
    return _ASSISTANT_REGISTRY.get_tools(name)


def assistant_tool_names(name: str) -> list[str]:
    """Return tool names available directly to an assistant.

    Args:
        name: Registered assistant name.

    Returns:
        Registered tool names in resolution order.
    """
    _configure_tools()
    return _ASSISTANT_REGISTRY.list_tool_names(name)


def assistant_reachable_tool_names(name: str) -> list[str]:
    """Return tools callable by an assistant or its handoff targets.

    Args:
        name: Root registered assistant name.

    Returns:
        Deduplicated tool names in handoff traversal order.
    """
    _configure_tools()
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


def create_assistant(
    name: str,
    *,
    model: object | None = None,
    instructions: Any | None = None,
    instructions_by_name: Mapping[str, Any] | None = None,
    output_type: type[Any] | None = None,
    context_provider: ContextProvider | None = None,
    skill_provider: SkillProvider | None = None,
) -> AssistantAgent:
    """Construct a fresh SDK graph with specification-owned prompt rendering.

    Args:
        name: Root registered assistant name.
        model: Optional model override propagated through the graph.
        instructions: Optional root instruction override.
        instructions_by_name: Optional instruction overrides by assistant name.
        output_type: Optional structured output type for the root agent.
        context_provider: Optional factual provider default shared by the graph.
        skill_provider: Optional workflow provider default shared by the graph.

    Returns:
        A fresh SDK agent and handoffs with built-in instruction callbacks.
        With AssistantRunContext they render permitted prepared resources;
        without it they return durable prompts. Explicit overrides take priority.
    """
    _configure_tools()
    agent = _build_assistant(
        _ASSISTANT_REGISTRY,
        name,
        model=model,
        instructions=instructions,
        instructions_by_name=instructions_by_name,
        output_type=output_type,
        context_provider=context_provider,
        skill_provider=skill_provider,
    )
    log_agent_graph(agent, task_prompt=_ASSISTANT_REGISTRY.get_spec(name).task_prompt)
    return agent


def render_assistant_input(name: str, input_text: str) -> str:
    """Apply an assistant's optional task wrapper to SDK run input.

    Args:
        name: Registered assistant name.
        input_text: Raw SDK run input.

    Returns:
        Input text with the optional task prompt applied.
    """
    return _render_input(_ASSISTANT_REGISTRY, name, input_text)


__all__ = [
    "ASSISTANT_SPECS_DIR",
    "AssistantAgent",
    "SPECS_DIR",
    "AssistantRegistry",
    "assistant_handoff_names",
    "assistant_reachable_tool_names",
    "assistant_spec",
    "assistant_skill_names",
    "assistant_tool_names",
    "assistant_tools",
    "build_assistant_instructions",
    "create_assistant",
    "list_assistants",
    "load_assistant_spec",
    "prepare_resources",
    "reload_assistant_specs",
    "render_assistant_input",
    "resolve_assistant_tools",
]
