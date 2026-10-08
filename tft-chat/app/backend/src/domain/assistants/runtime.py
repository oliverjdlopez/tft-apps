"""Prepare invocation resources and render context-backed SDK instructions."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from domain.assistants.utils import resource_query
from domain.runtime.models import PreparedResources

if TYPE_CHECKING:
    from domain.providers.models import ContextProvider, SkillProvider


async def prepare_resources(
    messages: Sequence[Mapping[str, str]],
    *,
    context_provider: ContextProvider,
    skill_provider: SkillProvider,
    set_number: int | None,
    timing: dict[str, Any] | None = None,
) -> PreparedResources:
    """Select references and skills once before starting a logical invocation.

    Args:
        messages: Conversation history used to derive the selector query.
        context_provider: Asynchronous selector for factual references.
        skill_provider: Asynchronous selector for supplemental workflows.
        set_number: Explicit TFT set used to scope factual references, if configured.
        timing: Optional request timing record receiving selector durations.

    Returns:
        Immutable selections reused by every model turn and handoff.
    """
    query = resource_query(messages)
    stage_started = time.perf_counter()
    references = (
        tuple(await context_provider.aselect(query, set_number=set_number))
        if query.strip()
        else ()
    )
    if timing is not None:
        timing["context_selection_ms"] = round(
            (time.perf_counter() - stage_started) * 1000, 3
        )
    stage_started = time.perf_counter()
    skills = tuple(await skill_provider.aselect(query))
    if timing is not None:
        timing["skill_selection_ms"] = round(
            (time.perf_counter() - stage_started) * 1000, 3
        )
    return PreparedResources(query=query, references=references, skills=skills)


__all__ = ["prepare_resources"]
