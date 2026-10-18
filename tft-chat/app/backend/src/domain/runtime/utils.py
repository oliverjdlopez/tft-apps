"""Small shared helpers for invocation lifecycle state."""

from __future__ import annotations

import json
from typing import Any
from collections.abc import Mapping, Sequence

# ---------------------------------------------------------------------------
# Activity hooks
#
# Keep argument decoding independent of the browser stream representation.
# ---------------------------------------------------------------------------


def decode_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Return object-shaped SDK tool arguments, or an empty safe fallback."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ---------------------------------------------------------------------------
# Stream lifecycle
#
# Keep SDK cancellation cleanup separate from browser-event translation.
# ---------------------------------------------------------------------------


async def cancel_streamed_result(result: Any, events: Any) -> None:
    """Cancel an interrupted SDK result and settle its public stream iterator.

    Args:
        result: SDK result, or a legacy test adapter without cancellation support.
        events: The original iterator, possibly suspended at a yielded event.
    """
    import asyncio
    from contextlib import suppress

    cancel = getattr(result, "cancel", None)
    if callable(cancel):
        cancel(mode="immediate")
    close = getattr(events, "aclose", None)
    if callable(close):
        with suppress(Exception, asyncio.CancelledError):
            await close()
    if callable(cancel):
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
