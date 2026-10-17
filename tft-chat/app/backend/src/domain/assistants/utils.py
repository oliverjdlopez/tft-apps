"""Implementation helpers for assistant execution and tool resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from domain.assistants.models import AssistantSpec


# -----------------------------------------------------------------------------
# Assistant execution
#
# Input assembly for an individual invocation.
# -----------------------------------------------------------------------------

def invocation_input(
    input: str | Sequence[Mapping[str, str]], task_prompt: str,
) -> str | list[dict[str, str]]:
    """Copy conversation history and prepare SDK input without modifying caller messages.

    Args:
        input: User text or conversation history.
        task_prompt: Root task wrapper, applied only to the latest user message.

    Returns:
        Wrapped text or a copied conversation with only its last user input wrapped.
    """
    if isinstance(input, str):
        return wrap_task_input(input, task_prompt)
    messages = [
        {"role": message["role"], "content": message["content"]}
        for message in input if message["role"] in {"user", "assistant"}
    ]
    for message in reversed(messages):
        if message["role"] == "user":
            message["content"] = wrap_task_input(message["content"], task_prompt)
            break
    return messages


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


# -----------------------------------------------------------------------------
# Registry construction
#
# Resolve declared tool access once for each registered definition.
# -----------------------------------------------------------------------------

def resolve_tools(spec: AssistantSpec) -> list[Any]:
    """Resolve an assistant specification to registered SDK tools.

    Args:
        spec: Assistant specification declaring tool names and groups.

    Returns:
        Deduplicated SDK tools in declared group and name order.

    Raises:
        KeyError: If a declared tool or tool group is not registered.
    """
    # Import at use time: the context tool imports assistant resource reads.
    from domain.tools import get_tool, get_tool_group, list_tools, tool_name

    if spec.include_all_tools:
        return list_tools()

    resolved: list[Any] = []
    seen: set[str] = set()
    for group_key in spec.tool_group_keys:
        for grouped_tool in get_tool_group(group_key).list_tools():
            name = tool_name(grouped_tool)
            if name not in seen:
                resolved.append(get_tool(name))
                seen.add(name)
    for name in spec.tool_names:
        tool = get_tool(name)
        if name not in seen:
            resolved.append(tool)
            seen.add(name)
    return resolved
