"""Small shared helpers for invocation lifecycle state."""

from __future__ import annotations

import json
from typing import Any


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
