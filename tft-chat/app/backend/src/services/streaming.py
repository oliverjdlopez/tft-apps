"""Framing for structured events embedded in streamed chat text."""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from common.serialization import model_jsonable, render_json_preview
from domain.tools.evidence import EvidenceStore

STREAM_EVENT_PREFIX = "[[chat_tft_event:"
STREAM_EVENT_SUFFIX = "]]"

logger = logging.getLogger(__name__)


def stream_event(event: dict[str, Any]) -> str:
    """Frame one structured event for the mixed chat response stream."""
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return (
        f"\n{STREAM_EVENT_PREFIX}"
        f"{base64.b64encode(payload).decode('ascii')}"
        f"{STREAM_EVENT_SUFFIX}\n"
    )


def _item_value(item: Any, attr: str, *, raw_attr: str | None = None) -> Any:
    """Read an SDK run-item value from its public or wrapped raw shape."""
    value = getattr(item, attr, None)
    if value is not None:
        return value
    raw_item = getattr(item, "raw_item", None)
    return getattr(raw_item, raw_attr or attr, None)


def _tool_call_arguments(item: Any) -> dict[str, Any]:
    """Decode a tool call's object-shaped JSON arguments."""
    raw_args = _item_value(item, "arguments")
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str):
        try:
            parsed = json.loads(raw_args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _text_delta(data: Any) -> str | None:
    """Return text only for an SDK output-text delta event."""
    if getattr(data, "type", None) == "response.output_text.delta":
        return getattr(data, "delta", None)
    return None


def _text_part_completed(data: Any) -> bool:
    """Return whether an SDK event ends one streamed output-text part.

    The browser needs this semantic boundary because HTTP response chunks do
    not correspond to the Responses API's content parts.
    """
    return getattr(data, "type", None) == "response.output_text.done"


async def stream_agent_events(
    result: Any,
    *,
    tools_by_name: Mapping[str, Mapping[str, Any]],
    request_id: str,
    trace_id: str,
    evidence_store: EvidenceStore | None = None,
    on_model_event: Callable[[], None] | None = None,
    on_text_delta: Callable[[], None] | None = None,
) -> AsyncIterator[str]:
    """Translate SDK events and optionally mark first model/text arrival.

    Args:
        result: Streamed Agents SDK run.
        tools_by_name: Browser-safe metadata for reachable tools.
        request_id: HTTP request identifier used by diagnostic logs.
        trace_id: SDK trace identifier used by activity events.
        evidence_store: Optional request-local presentation store.
        on_model_event: Called when the first raw model response event arrives.
        on_text_delta: Called when the first nonempty text delta arrives.
    """
    called: dict[str, dict[str, Any]] = {}
    async for event in result.stream_events():
        if event.type == "raw_response_event":
            if on_model_event is not None:
                on_model_event()
            delta = _text_delta(event.data)
            if delta:
                if on_text_delta is not None:
                    on_text_delta()
                yield delta
            if _text_part_completed(event.data):
                yield stream_event({"type": "text_part_complete"})
            continue

        if event.type != "run_item_stream_event":
            continue
        item = getattr(event, "item", None)
        if event.name == "tool_called":
            name = _item_value(item, "tool_name", raw_attr="name")
            if not name:
                continue
            call_id = _item_value(item, "call_id") or name
            called[call_id] = {
                "name": name,
                "arguments": _tool_call_arguments(item),
                "started_at": time.perf_counter(),
            }
            logger.info(
                "chat tool called request_id=%s trace_id=%s tool=%s call_id=%s",
                request_id,
                trace_id,
                name,
                call_id,
            )
            continue

        if event.name == "tool_output":
            call_id = _item_value(item, "call_id")
            call = called.get(call_id or "", {})
            name = call.get("name") or _item_value(
                item, "tool_name", raw_attr="name"
            )
            if not name:
                continue
            started_at = call.get("started_at")
            elapsed_ms = (
                (time.perf_counter() - started_at) * 1000
                if started_at is not None
                else None
            )
            logger.info(
                "chat tool completed request_id=%s trace_id=%s tool=%s call_id=%s elapsed_ms=%s",
                request_id,
                trace_id,
                name,
                call_id or "unknown",
                f"{elapsed_ms:.1f}" if elapsed_ms is not None else "unknown",
            )
            output = getattr(item, "output", None)
            model_output = model_jsonable(output)
            if name == "present_evidence":
                presentation = (
                    evidence_store.presentations.get(call_id)
                    if evidence_store else None
                )
                if presentation is not None:
                    try:
                        # The model receives only an acknowledgement. Stream the
                        # validated store object directly to preserve precision.
                        yield stream_event({
                            "type": "presentation",
                            "presentation": presentation.model_dump(mode="json"),
                        })
                    except (ValueError, TypeError):
                        yield stream_event({"type": "presentation_error", "error": "Evidence view unavailable."})
                else:
                    yield stream_event({"type": "presentation_error", "error": "Evidence view unavailable."})
            yield stream_event(
                {
                    "type": "tool",
                    "name": name,
                    "description": tools_by_name.get(name, {}).get("description")
                    or "",
                    "arguments": call.get("arguments") or {},
                    "result": model_output,
                    "result_preview": render_json_preview(model_output, max_chars=1800),
                    "error": None,
                }
            )
            continue

        if event.name in ("handoff_occured", "handoff_occurred"):
            target = getattr(getattr(item, "target_agent", None), "name", None)
            if target:
                yield stream_event(
                    {
                        "type": "handoff",
                        "name": target,
                        "description": (
                            f"Conversation handed off to the {target} assistant."
                        ),
                        "arguments": {},
                        "result_preview": None,
                        "error": None,
                    }
                )
