"""Small shared helpers for invocation lifecycle state."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents import RunResultStreaming, StreamEvent

# ---------------------------------------------------------------------------
# Activity hooks
#
# Keep argument decoding independent of the browser stream representation.
# ---------------------------------------------------------------------------


def decode_tool_arguments(arguments: str) -> dict[str, Any]:
    """Return object-shaped SDK tool arguments, or an empty safe fallback."""
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


# ---------------------------------------------------------------------------
# Stream lifecycle
#
# Keep SDK cancellation cleanup separate from browser-event translation.
# ---------------------------------------------------------------------------


async def cancel_streamed_result(
    result: RunResultStreaming, events: AsyncIterator[StreamEvent] | None,
) -> None:
    """Cancel an interrupted SDK result and settle its public stream iterator.

    Args:
        result: SDK result whose background execution must stop.
        events: Original iterator, or None if consumption has not started.
    """
    result.cancel(mode="immediate")
    # The SDK exposes AsyncIterator, which does not require an aclose method.
    close = getattr(events, "aclose", None)
    if callable(close):
        with suppress(Exception, asyncio.CancelledError):
            await close()
    # The SDK requires consumption after cancel. A new iterator also waits
    # for cleanup when cancellation already closed the original iterator.
    with suppress(Exception, asyncio.CancelledError):
        async for _event in result.stream_events():
            pass


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
    """Apply task instructions to a string input or the latest user message.

    Args:
        input_text: Original user input.
        task_prompt: Optional task instructions belonging to the root.

    Returns:
        Wrapped input, or the original text when the wrapper is empty.
    """
    if not task_prompt.strip():
        return input_text
    return f"{task_prompt.strip()}\n\n## Input\n\n{input_text}".strip()
