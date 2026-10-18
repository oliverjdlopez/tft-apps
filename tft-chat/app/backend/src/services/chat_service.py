"""Chat configuration, instruction preparation, and streamed agent execution."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import aclosing
from typing import Any

from agents import MaxTurnsExceeded
from agents.run_internal.items import run_items_to_input_items
from agents.tracing import trace

from core.config import load_config
from common.langfuse_tracing import development_trace
from domain.assistants import (
    SPECS_DIR,
    Assistant,
)
from domain.assistants.constants import AssistantName
from domain.assistants.registry import current_registry
from domain.runtime.utils import invocation_input
from domain.runtime.execution import create_context, run_streamed
from domain.model_catalog import chat_model_specs
from domain.tools import list_tool_group_metadata, list_tool_metadata
from services.streaming import stream_agent_events, stream_event

logger = logging.getLogger(__name__)

CHAT_ASSISTANT_NAME = AssistantName.CHAT

ChatMessage = Mapping[str, str]


def _agent_input(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """Keep only SDK-supported conversation roles."""
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]


async def stream_chat(
    messages: Sequence[ChatMessage],
    system: str | None,
    model_name: str,
    *,
    model: Any,
    max_tool_rounds: int,
    request_id: str | None = None,
    assistant_name: str = CHAT_ASSISTANT_NAME,
    timing: dict[str, Any] | None = None,
) -> AsyncIterator[str]:
    """Prepare and execute one routed chat request as text and UI events.

    Args:
        messages: Conversation messages accepted by the Agents SDK.
        system: Optional caller instructions prepended to the root prompt.
        model_name: Public model identifier recorded in trace metadata.
        model: SDK model implementation used across the assistant graph.
        max_tool_rounds: Maximum tool-call rounds before forced finalization.
        request_id: Optional request identifier for logs and stream events.
        assistant_name: Registered assistant used as the root graph node.
        timing: Optional timing record shared with the HTTP route.

    Yields:
        Plain assistant text and encoded browser activity events.
    """
    config = load_config()
    request_label = request_id or "unknown"
    # Use one definition snapshot for execution and its UI/trace metadata.
    registry = current_registry()
    setup_started = time.perf_counter()
    assistant = await asyncio.to_thread(
        Assistant.from_name, assistant_name, registry=registry, model=model,
    )
    run_input = invocation_input(messages, assistant.spec.task_prompt)
    run_context = await asyncio.to_thread(
        create_context, assistant,
        surface="chat", request_id=request_label, system=system, timing=timing,
    )
    if timing is not None:
        timing['agent_setup_ms'] = round((time.perf_counter() - setup_started) * 1000, 3)
    reachable_tool_names = list(registry.reachable_tool_names[assistant_name])
    setup_started = time.perf_counter()
    tools_by_name = {
        tool["name"]: tool for tool in list_tool_metadata(reachable_tool_names)
    }
    started_at = time.perf_counter()
    reachable_groups = list_tool_group_metadata(reachable_tool_names)
    with development_trace(_agent_input(messages), enabled=config.chat.langfuse_tracing) as development, trace(
        "chat_tft",
        metadata={
            "assistant": assistant_name,
            "model": model_name,
            "message_count": str(len(messages)),
            "direct_tool_names": ",".join(
                registry.tool_names[assistant_name]
            ),
            "tool_names": ",".join(reachable_tool_names),
            "tool_group_names": ",".join(
                (group.get("key") or group.get("name") or "")
                for group in reachable_groups
            ),
            "context_sources": ",".join(
                dict.fromkeys(read.path for read in run_context.activity.resource_reads.values() if read.kind != 'skill')
            ),
        },
    ) as chat_trace:
        trace_label = chat_trace.trace_id
        yield stream_event(
            {"type": "trace", "name": chat_trace.name, "trace_id": trace_label}
        )
        agent = assistant
        if timing is not None:
            timing["agent_setup_ms"] = round(
                timing.get("agent_setup_ms", 0)
                + (time.perf_counter() - setup_started) * 1000,
                3,
            )

        def mark_model_event() -> None:
            """Record the time of the first event from the model stream."""
            if timing is not None and "first_model_event_ms" not in timing:
                timing["first_model_event_ms"] = round(
                    (time.perf_counter() - timing["started_at"]) * 1000, 3
                )

        def mark_text_delta() -> None:
            """Record the time of the first assistant text delta."""
            if timing is not None and "first_text_delta_ms" not in timing:
                timing["first_text_delta_ms"] = round(
                    (time.perf_counter() - timing["started_at"]) * 1000, 3
                )
        try:
            async with run_streamed(
                agent, run_input, context=run_context,
                max_turns=max_tool_rounds + 1, input_prepared=True,
            ) as result:
                async with aclosing(stream_agent_events(
                    result,
                    tools_by_name=tools_by_name,
                    request_id=request_label,
                    trace_id=trace_label,
                    run_context=run_context,
                    on_model_event=mark_model_event,
                    on_text_delta=mark_text_delta,
                )) as events:
                    async for chunk in events:
                        yield chunk
        except MaxTurnsExceeded as e:
            logger.warning(
                "chat tool limit reached; generating tool-free response request_id=%s trace_id=%s elapsed_ms=%.1f",
                request_label,
                trace_label,
                (time.perf_counter() - started_at) * 1000,
            )
            final_agent = agent.clone(
                name=(
                    "chat_tft_final_response"
                    if assistant_name == CHAT_ASSISTANT_NAME
                    else f"{assistant_name}_final_response"
                ),
                model=model,
                model_settings=agent.model_settings,
                tools=[],
                handoffs=[],
            )
            run_data = getattr(e, "run_data", None)
            new_items = getattr(run_data, "new_items", None)
            replay_items = run_items_to_input_items(new_items) if new_items else []
            stop_prompt = (
                SPECS_DIR / CHAT_ASSISTANT_NAME / "tool-loop-stop.md"
            ).read_text(encoding="utf-8").strip()
            async with run_streamed(
                final_agent,
                input=[
                    *run_input,
                    *replay_items,
                    {"role": "user", "content": stop_prompt},
                ],
                max_turns=1,
                context=run_context,
                input_prepared=True,
            ) as final_result:
                async with aclosing(stream_agent_events(
                    final_result,
                    tools_by_name={},
                    request_id=request_label,
                    trace_id=trace_label,
                    run_context=run_context,
                    on_model_event=mark_model_event,
                    on_text_delta=mark_text_delta,
                )) as events:
                    async for chunk in events:
                        yield chunk
        if development is not None:
            try:
                development.update(output=str((final_result if 'final_result' in locals() else result).final_output))
            except Exception:
                logger.warning('Unable to attach the development conversation output')


def resolve_chat_assistant(header_value: str | None) -> str:
    """Resolve an optional HTTP header to a registered chat root assistant.

    Args:
        header_value: Value supplied in the ``X-Chat-Assistant`` header.

    Returns:
        The default chat assistant or the validated registered assistant name.

    Raises:
        LookupError: If a supplied header is blank or names no assistant.
    """
    if header_value is None:
        return CHAT_ASSISTANT_NAME
    assistant_name = header_value.strip()
    if not assistant_name:
        raise LookupError("X-Chat-Assistant must name a registered assistant.")
    try:
        current_registry().get_spec(assistant_name)
    except KeyError:
        raise LookupError(
            f"Unknown chat assistant {assistant_name!r}."
        ) from None
    return assistant_name


def chat_config(
    database_status: dict[str, object] | None = None,
) -> dict[str, Any]:
    """Return the model, tool, and runtime status needed by the chat UI.

    Args:
        database_status: Optional browser-safe database startup state.

    Returns:
        Browser configuration and availability metadata.
    """
    config = load_config()
    model_specs = chat_model_specs(config)
    registry = current_registry()
    tool_names = list(registry.reachable_tool_names[CHAT_ASSISTANT_NAME])
    tools = list_tool_metadata(tool_names)
    return {
        "composition_workbench": config.chat.composition_workbench,
        "flowchart_source": config.chat.flowchart_source,
        # Browser asset lookup uses the configured set without exposing any
        # database scope or player-specific identifiers.
        "asset_context": {
            "set_number": config.chat.set_number,
        },
        "default_assistant": CHAT_ASSISTANT_NAME,
        "assistants": list(registry.assistant_names),
        "default_model": config.models.openai_model,
        "models": [
            {
                "id": model.id,
                "label": model.label,
                "model": model.id,
                "provider": model.provider,
                "description": model.description,
                "tier": model.tier,
                "is_default": model.is_default,
                "key_configured": bool(
                    config.secrets.openai_api_key
                    if model.provider == "openai"
                    else config.secrets.anthropic_api_key
                ),
            }
            for model in model_specs
        ],
        "tools": tools,
        "tool_groups": list_tool_group_metadata(tool_names),
        "database": dict(
            database_status
            or {"available": None, "configured": None, "warning": None}
        ),
    }
