"""Construct live runtime assistants from development-owned definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from domain.assistants import Assistant, BaseAssistant
from domain.assistants.registry import AssistantRegistry
from devtools.assistants.capture import AssistantDefinitions, registry_from_capture


def _replace_instructions(
    definitions: AssistantDefinitions,
    replacements: Mapping[str, str],
) -> AssistantDefinitions:
    """Return a registry with development prompt candidates applied."""
    registry = definitions.registry
    for name in replacements:
        registry.get_spec(name)
    candidate = AssistantRegistry(
        [
            replace(spec, system_prompt=replacements[spec.name])
            if spec.name in replacements
            else spec
            for spec in (
                registry.get_spec(name) for name in registry.assistant_names
            )
        ]
    )
    return AssistantDefinitions(
        registry=candidate,
        source_files={
            name: dict(files)
            for name, files in definitions.source_files.items()
        },
        resolved_models=dict(definitions.resolved_models),
    )


def assistant_from_registry(
    registry: AssistantRegistry | AssistantDefinitions,
    name: str,
    *,
    prompt_candidates: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> BaseAssistant:
    """Build an assistant from isolated definitions and prompt candidates."""
    definitions = (
        registry
        if isinstance(registry, AssistantDefinitions)
        else AssistantDefinitions(registry=registry)
    )
    candidate = (
        _replace_instructions(definitions, prompt_candidates)
        if prompt_candidates is not None
        else definitions
    )
    return Assistant(
        name,
        registry=candidate.registry,
        resolved_models=candidate.resolved_models,
        **kwargs,
    )


def assistant_from_capture(
    graph: dict[str, Any],
    name: str,
    *,
    prompt_candidates: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> BaseAssistant:
    """Build an ordinary runtime assistant from a verified captured graph."""
    return assistant_from_registry(
        registry_from_capture(graph),
        name,
        prompt_candidates=prompt_candidates,
        **kwargs,
    )

