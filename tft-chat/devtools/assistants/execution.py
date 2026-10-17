"""Construct live runtime assistants from development-owned definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from domain.assistants import Assistant
from domain.assistants.registry import AssistantRegistry
from domain.assistants.utils import configure_tools
from devtools.assistants.capture import registry_from_capture


def _replace_instructions(
    registry: AssistantRegistry,
    replacements: Mapping[str, str],
) -> AssistantRegistry:
    """Return a registry with development prompt candidates applied."""
    for name in replacements:
        registry.get_spec(name)
    candidate = AssistantRegistry(
        [
            replace(spec, system_prompt=replacements[spec.name])
            if spec.name in replacements
            else spec
            for spec in (
                registry.get_spec(name) for name in registry.list_assistants()
            )
        ]
    )
    configure_tools(candidate)
    candidate.resolved_models = dict(registry.resolved_models)
    candidate.source_files = {
        name: dict(files)
        for name, files in getattr(registry, "source_files", {}).items()
    }
    return candidate


def assistant_from_registry(
    registry: AssistantRegistry,
    name: str,
    *,
    prompt_candidates: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> Assistant:
    """Build an assistant from isolated definitions and prompt candidates."""
    candidate = (
        _replace_instructions(registry, prompt_candidates)
        if prompt_candidates is not None
        else registry
    )
    return Assistant(name, registry=candidate, **kwargs)


def assistant_from_capture(
    graph: dict[str, Any],
    name: str,
    *,
    prompt_candidates: Mapping[str, str] | None = None,
    **kwargs: Any,
) -> Assistant:
    """Build an ordinary runtime assistant from a verified captured graph."""
    return assistant_from_registry(
        registry_from_capture(graph),
        name,
        prompt_candidates=prompt_candidates,
        **kwargs,
    )

