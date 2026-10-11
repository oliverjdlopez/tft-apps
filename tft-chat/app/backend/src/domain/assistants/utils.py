"""Implementation helpers for assistant invocation assembly."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from domain.runtime.models import AssistantRunContext

if TYPE_CHECKING:
    from agents import Agent, RunContextWrapper

    from domain.assistants.specs import AssistantSpec
    from domain.assistants.models import AssistantInvocation
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
    spec: AssistantSpec, *, root: bool
) -> Callable[[RunContextWrapper[Any], Agent[Any]], str]:
    """Bind an agent's specification without capturing invocation state.

    Args:
        spec: Specification snapshot belonging to this constructed agent.
        root: Whether to apply root-only caller instructions and exclude skills.

    Returns:
        A synchronous SDK callback that renders only preselected resources.
        Legacy callers without typed context receive the durable prompt.
    """
    def render(
        ctx: RunContextWrapper[Any],
        agent: Agent[Any],
    ) -> str:
        """Render this target's instructions from its shared invocation context.

        Args:
            ctx: SDK wrapper around the application's explicit run context.
            agent: SDK agent requesting instructions for its next model turn.

        Returns:
            Durable policy joined with this target's permitted request layers.
        """
        del agent
        context = ctx.context
        if not isinstance(context, AssistantRunContext):
            return spec.system_prompt
        started = time.perf_counter()
        base_instructions = spec.system_prompt
        if root and context.runtime.system:
            base_instructions = f"{context.runtime.system}\n\n{base_instructions}"
        instructions = render_instruction_layers(
            spec,
            context_provider=context.context_provider,
            skill_provider=context.skill_provider,
            skills=() if root else context.resources.skills,
            base_instructions=base_instructions,
            references=(
                context.resources.references if context.resources.query.strip() else ()
            ),
        )
        if context.timing is not None:
            # SDK callbacks can run on every model step, so this metric includes
            # each render while selection timings remain once per invocation.
            context.timing["instruction_assembly_ms"] = round(
                context.timing.get("instruction_assembly_ms", 0.0)
                + (time.perf_counter() - started) * 1000,
                3,
            )
        return instructions

    return render


# ---------------------------------------------------------------------------
# Assistant consumer preparation
#
# Conversation copying and provenance recording belong to the prepared run,
# independent of HTTP transports and evaluation result serialization.
# ---------------------------------------------------------------------------


def invocation_input(
    input: str | Sequence[Mapping[str, str]], task_prompt: str,
) -> tuple[list[dict[str, str]], str | list[dict[str, str]]]:
    """Prepare selector history and SDK input without modifying caller messages.

    Args:
        input: User text or conversation history.
        task_prompt: Root task wrapper, applied only to the latest user message.

    Returns:
        Unwrapped selector messages and wrapped SDK input, respectively.
    """
    messages = ([{"role": "user", "content": input}] if isinstance(input, str) else [
        {"role": message["role"], "content": message["content"]}
        for message in input if message["role"] in {"user", "assistant"}
    ])
    run_messages = [dict(message) for message in messages]
    if task_prompt.strip():
        for message in reversed(run_messages):
            if message["role"] == "user":
                message["content"] = wrap_task_input(message["content"], task_prompt)
                break
    return messages, run_messages[0]["content"] if isinstance(input, str) else run_messages


def wrap_task_input(input_text: str, task_prompt: str) -> str:
    """Apply a task wrapper consistently for prepared and legacy consumers.

    Args:
        input_text: Original user input.
        task_prompt: Optional task instructions belonging to the root.

    Returns:
        Wrapped input, or the original text when the wrapper is empty.
    """
    if not task_prompt.strip():
        return input_text
    return f"{task_prompt.strip()}\n\n## Input\n\n{input_text}".strip()


def record_instructions(invocation: AssistantInvocation) -> None:
    """Record actual model-facing instructions on one prepared graph.

    Args:
        invocation: Fresh invocation receiving instruction and model provenance.
    """
    from domain.assistants.token_logging import agent_model_name

    seen: set[int] = set()

    def visit(agent: Agent[Any]) -> None:
        """Wrap each graph object once, retaining its own bound callback.

        Args:
            agent: Root or handoff whose model calls should be recorded.
        """
        if id(agent) in seen:
            return
        seen.add(id(agent))
        invocation.model_settings[agent.name] = {
            "model": agent_model_name(agent),
            "settings": agent.model_settings.to_json_dict(),
        }
        callback = agent.instructions

        def render(wrapper: RunContextWrapper[Any], target: Agent[Any]) -> str:
            """Capture text after this target's dynamic rendering policy.

            Args:
                wrapper: SDK wrapper containing the invocation context.
                target: Agent requesting model instructions.

            Returns:
                The original rendered text, unchanged for model execution.
            """
            text = callback(wrapper, target) if callable(callback) else callback
            invocation.instructions[target.name] = text
            return text

        agent.instructions = render
        for child in agent.handoffs:
            visit(child)

    visit(invocation.agent)
