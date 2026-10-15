"""Implementation helpers for assistant invocation assembly."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from domain.assistants.constants import AssistantName
from domain.runtime.models import AssistantRunContext, PreparedResources

if TYPE_CHECKING:
    from agents import Agent, RunContextWrapper

    from domain.assistants.specs import AssistantSpec
    from domain.assistants.models import AssistantInvocation


# ---------------------------------------------------------------------------
# Runtime resource preparation and instruction rendering
#
# Descriptions support discovery; complete bodies remain in read tool results.
# Instruction rendering never selects or injects resource contents.
# ---------------------------------------------------------------------------

def render_instruction_layers(
    spec: AssistantSpec,
    *,
    resources: PreparedResources | None = None,
    base_instructions: str | None = None,
) -> str:
    """Append only resource descriptions; full bodies require a read tool call.

    Args:
        spec: Target specification whose frozen resource access applies.
        resources: Invocation-local resource catalogue and permissions.
        base_instructions: Optional durable prompt replacement.

    Returns:
        Durable instructions followed by the permitted resource catalogue.
    """
    from domain.resources.catalogue import render_catalogue

    parts = [spec.system_prompt if base_instructions is None else base_instructions]
    if resources is not None:
        parts.append(render_catalogue(resources, spec.name))
    return "\n\n".join(part.strip() for part in parts if part.strip())


def can_receive_instruction_resources(
    spec: AssistantSpec,
    configured_names: tuple[str, ...] | None,
) -> bool:
    """Apply graph-level eligibility before an instruction-resource allowlist.

    Args:
        spec: Assistant whose instructions are being rendered.
        configured_names: Skill or playbook allowlist from the specification.

    Returns:
        Whether the assistant may receive that resource kind in this graph.
    """
    # `None` means unrestricted; an empty tuple explicitly denies this category.
    # Chat remains a router even if its spec declares a broader allowlist.
    return (
        spec.name != AssistantName.CHAT
        and configured_names != ()
        and (spec.repository_context or bool(configured_names))
    )


def instruction_callback(
    spec: AssistantSpec, *, root: bool
) -> Callable[[RunContextWrapper[Any], Agent[Any]], str]:
    """Bind an agent's specification without capturing invocation state.

    Args:
        spec: Specification snapshot belonging to this constructed agent.
        root: Whether to apply the root-only caller system prefix.

    Returns:
        A synchronous SDK callback that renders only resource metadata.
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
            spec, resources=context.resources, base_instructions=base_instructions,
        )
        if context.timing is not None:
            # SDK callbacks can run on every model step, so this metric includes
            # each render while catalogue loading happens once per invocation.
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
    """Copy conversation history and prepare SDK input without modifying caller messages.

    Args:
        input: User text or conversation history.
        task_prompt: Root task wrapper, applied only to the latest user message.

    Returns:
        Original copied messages and wrapped SDK input, respectively.
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


# ---------------------------------------------------------------------------
# Assistant registry tool wiring
#
# Callers provide the registry so invocation construction never imports its
# public package facade, which re-exports the Assistant class.
# ---------------------------------------------------------------------------


def configure_tools(registry) -> None:
    """Connect an assistant registry to the public tool registry API.

    Args:
        registry: Registry receiving the tool lookup operations.
    """
    from domain.tools import get_tool, get_tool_group, list_tools, tool_name

    registry.configure_tools(
        get_tool=get_tool,
        get_tool_group=get_tool_group,
        list_tools=list_tools,
        tool_name=tool_name,
    )
