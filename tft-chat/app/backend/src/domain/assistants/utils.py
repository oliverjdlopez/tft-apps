"""Implementation helpers for assistant invocation assembly."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents import RunContextWrapper

    from domain.assistants.agent import AssistantAgent
    from domain.assistants.specs import AssistantSpec
    from domain.providers.models import (
        ContextProvider,
        ContextSnippet,
        SkillDefinition,
        SkillProvider,
    )


# ---------------------------------------------------------------------------
# Runtime resource preparation and instruction rendering
#
# Selection happens before execution; these helpers keep rendering independent
# of selectors and invocation activity.
# ---------------------------------------------------------------------------

FOLLOW_UP_RE = re.compile(
    r"\b(?:it|its|they|them|their|this|that|these|those|same|one|ones|above|"
    r"previous)\b"
    r"|\b(?:what|how)\s+about\b"
    r"|\b(?:and|also)\s+(?:for|with|about|then)\b",
    re.IGNORECASE,
)


def resource_query(messages: Sequence[Mapping[str, str]]) -> str:
    """Retain recent user history only when the latest prompt is a follow-up.

    Args:
        messages: Conversation history containing user and assistant messages.

    Returns:
        The latest nonempty user prompt, or the last four for a follow-up.
    """
    prompts = [
        message["content"].strip()
        for message in messages
        if message["role"] == "user"
    ]
    prompts = [prompt for prompt in prompts if prompt]
    if not prompts:
        return ""
    latest = prompts[-1]
    if len(prompts) == 1 or not FOLLOW_UP_RE.search(latest):
        return latest
    return " ".join(prompts[-4:])


def render_instruction_layers(
    spec: AssistantSpec,
    *,
    context_provider: ContextProvider,
    skill_provider: SkillProvider,
    references: Sequence[ContextSnippet] = (),
    skills: Sequence[SkillDefinition] = (),
    base_instructions: str | None = None,
) -> str:
    """Render already selected resources under one specification's access policy.

    Args:
        spec: Agent specification whose eligibility rules apply.
        context_provider: Renderer for permitted factual references.
        skill_provider: Renderer for permitted workflow material.
        references: Complete references selected for this invocation.
        skills: Skills selected for this invocation.
        base_instructions: Optional replacement for the durable prompt.

    Returns:
        Durable instructions followed by permitted resource layers.
    """
    # Enforce access at the rendering boundary even when resources were selected
    # by another caller or shared by agents with different permissions.
    allowed_skills = tuple(
        skill for skill in skills
        if spec.skill_names is None or skill.name in spec.skill_names
    )
    parts = [(base_instructions or spec.system_prompt).strip()]
    if spec.repository_context and references:
        parts.append(context_provider.render(references))
    if allowed_skills:
        parts.append(skill_provider.render(allowed_skills))
    return "\n\n".join(part for part in parts if part).strip()


def instruction_callback(
    ctx: RunContextWrapper[Any], agent: AssistantAgent,
) -> str:
    """Dispatch SDK instruction rendering through the actual executing agent.

    Args:
        ctx: SDK wrapper around the invocation's local context.
        agent: Assistant requesting instructions for its next model turn.

    Returns:
        This agent's durable policy and permitted prepared resource layers.
    """
    # A shared function follows SDK clones; a copied bound method could keep
    # rendering through the original agent's specification or providers.
    return agent.render_instructions(ctx.context)
