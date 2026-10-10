"""Internal construction helpers for fresh SDK assistant graphs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from core.config import load_config
from domain.assistants.agent import AssistantAgent
from domain.assistants.registry import AssistantRegistry, assistant_registry
from domain.assistants.utils import render_instruction_layers
from domain.providers.context import (
    DEFAULT_CONTEXT_PROVIDER,
    ContextProvider,
    ContextSnippet,
)
from domain.providers.skills import (
    DEFAULT_SKILL_PROVIDER,
    SkillDefinition,
    SkillProvider,
)


def build_assistant(
    registry: AssistantRegistry,
    name: str,
    *,
    model: object | None = None,
    instructions: Any | None = None,
    instructions_by_name: Mapping[str, Any] | None = None,
    output_type: type[Any] | None = None,
    context_provider: ContextProvider | None = None,
    skill_provider: SkillProvider | None = None,
) -> AssistantAgent:
    """Construct a fresh graph with each agent's context policy installed.

    Args:
        registry: Assistant registry used for specs, handoffs, and tools.
        name: Root registered assistant name.
        model: Optional model override propagated through the graph.
        instructions: Optional root instruction override.
        instructions_by_name: Optional instruction overrides by assistant name.
        output_type: Optional structured output type for the root agent.
        context_provider: Optional factual provider default for the entire graph.
        skill_provider: Optional workflow provider default for the entire graph.

    Returns:
        A fresh SDK agent and handoffs with default instruction renderers.
        Explicit instruction overrides take precedence over those renderers.

    Raises:
        ValueError: If the handoff graph contains a cycle.
    """
    instruction_map = dict(instructions_by_name or {})
    if instructions is not None:
        instruction_map[name] = instructions

    provider_defaults: dict[str, Any] = {}
    if context_provider is not None:
        provider_defaults["context_provider"] = context_provider
    if skill_provider is not None:
        provider_defaults["skill_provider"] = skill_provider

    def build(candidate: str, path: tuple[str, ...]) -> AssistantAgent:
        """Build one assistant and its handoff descendants.

        Args:
            candidate: Assistant currently being constructed.
            path: Ancestor names used for cycle detection.

        Returns:
            A fresh SDK agent for the candidate.

        Raises:
            ValueError: If the candidate already occurs in the path.
        """
        if candidate in path:
            cycle = " -> ".join((*path, candidate))
            raise ValueError(f"assistant handoff cycle: {cycle}")
        spec = registry.get_spec(candidate)
        handoffs = [
            build(handoff_name, (*path, candidate))
            for handoff_name in registry.get_handoff_names(candidate)
        ]
        return AssistantAgent(
            spec=spec,
            is_root=not path,
            name=spec.name,
            handoff_description=spec.handoff_description,
            instructions=instruction_map.get(candidate),
            model=spec.resolved_model() if model is None else model,
            model_settings=spec.model_settings(),
            tools=registry.resolve_tools(spec),
            handoffs=handoffs,
            output_type=output_type if candidate == name else None,
            **provider_defaults,
        )

    return build(name, ())


def render_input(
    registry: AssistantRegistry,
    name: str,
    input_text: str,
) -> str:
    """Apply an assistant specification's optional task wrapper.

    Args:
        registry: Assistant registry used to load the specification.
        name: Registered assistant name.
        input_text: Raw SDK run input.

    Returns:
        Input text with the optional task prompt applied.
    """
    task_prompt = registry.get_spec(name).task_prompt.strip()
    if not task_prompt:
        return input_text
    return f"{task_prompt}\n\n## Input\n\n{input_text}".strip()


def build_assistant_instructions(
    assistant_name: str,
    query: str,
    *,
    context_provider: ContextProvider = DEFAULT_CONTEXT_PROVIDER,
    skill_provider: SkillProvider = DEFAULT_SKILL_PROVIDER,
    skills: Sequence[SkillDefinition] | None = None,
    base_instructions: str | None = None,
    set_number: int | None = None,
    references: Sequence[ContextSnippet] | None = None,
) -> str:
    """Render one assistant's durable and request-specific instructions.

    Args:
        assistant_name: Registered assistant whose context policy is applied.
        query: User query used to select repository context.
        context_provider: Provider used to select and render repository context.
        skill_provider: Provider used to render selected skills.
        skills: Skills selected for this invocation.
        base_instructions: Optional replacement for the assistant system prompt.
        set_number: Optional TFT set override for context selection.
        references: Optional preselected repository context.

    Returns:
        The assembled instruction text for the assistant invocation.
    """
    spec = assistant_registry.get_spec(assistant_name)
    selected_references: tuple[ContextSnippet, ...] = ()
    if spec.repository_context and query.strip():
        if references is not None:
            selected_references = tuple(references)
        else:
            # Prepared invocations already chose their set at the boundary.
            # Only standalone selection needs the legacy configuration fallback.
            effective_set = (
                load_config().chat.set_number if set_number is None else set_number
            )
            selected_references = tuple(
                context_provider.select(query, set_number=effective_set)
            )
    return render_instruction_layers(
        spec,
        context_provider=context_provider,
        skill_provider=skill_provider,
        references=selected_references,
        skills=skills or (),
        base_instructions=base_instructions,
    )


__all__ = ["build_assistant", "build_assistant_instructions", "render_input"]
