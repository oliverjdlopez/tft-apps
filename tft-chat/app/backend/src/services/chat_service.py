"""Chat configuration, instruction preparation, and streamed agent execution."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from agents import Agent, MaxTurnsExceeded, Runner
from domain.tools.evidence import EvidenceStore
from agents.run_internal.items import run_items_to_input_items
from agents.tracing import trace

from core.config import load_config
from common.langfuse_tracing import development_trace
from domain.assistants import (
    SPECS_DIR,
    assistant_handoff_names,
    assistant_reachable_tool_names,
    assistant_spec,
    assistant_tool_names,
    build_assistant_instructions,
    create_assistant,
    list_assistants,
)
from domain.assistants.constants import AssistantName
from domain.providers.context import (
    DEFAULT_CONTEXT_PROVIDER,
    ContextProvider,
    ContextSnippet,
)
from domain.providers.skills import (
    DEFAULT_SKILL_PROVIDER,
    SkillDefinition,
    SkillProvider,
)
from domain.model_catalog import chat_model_specs
from domain.tools import list_tool_group_metadata, list_tool_metadata
from services.streaming import stream_agent_events, stream_event

logger = logging.getLogger(__name__)

CHAT_ASSISTANT_NAME = AssistantName.CHAT
_FOLLOW_UP_RE = re.compile(
    r"\b(?:it|its|they|them|their|this|that|these|those|same|one|ones|above|"
    r"previous)\b"
    r"|\b(?:what|how)\s+about\b"
    r"|\b(?:and|also)\s+(?:for|with|about|then)\b",
    re.IGNORECASE,
)

ChatMessage = Mapping[str, str]


def _agent_input(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    """Keep only SDK-supported conversation roles."""
    return [
        {"role": message["role"], "content": message["content"]}
        for message in messages
        if message["role"] in {"user", "assistant"}
    ]


def _chat_query(messages: Sequence[ChatMessage]) -> str:
    """Use recent user history only when the latest turn is a follow-up."""
    prompts = [
        message["content"].strip()
        for message in messages
        if message["role"] == "user"
    ]
    prompts = [prompt for prompt in prompts if prompt]
    if not prompts:
        return ""
    latest = prompts[-1]
    if len(prompts) == 1 or not _FOLLOW_UP_RE.search(latest):
        return latest
    return " ".join(prompts[-4:])


async def _build_chat_instructions(
    messages: Sequence[ChatMessage],
    system: str | None,
    *,
    assistant_name: str = CHAT_ASSISTANT_NAME,
    context_provider: ContextProvider = DEFAULT_CONTEXT_PROVIDER,
    skill_provider: SkillProvider = DEFAULT_SKILL_PROVIDER,
    timing: dict[str, Any] | None = None,
) -> tuple[
    str,
    dict[str, str],
    tuple[ContextSnippet, ...],
    tuple[SkillDefinition, ...],
]:
    """Select request resources and prepare root and handoff instructions.

    Args:
        messages: Conversation messages used to select request resources.
        system: Optional caller instructions prepended to the root prompt.
        assistant_name: Registered assistant used as the root graph node.
        context_provider: Repository context selector and renderer.
        skill_provider: Repository skill selector and renderer.
        timing: Optional request timing record to populate.

    Returns:
        Root instructions, handoff overrides, context references, and skills.
    """
    query = _chat_query(messages)
    set_number = load_config().chat.set_number
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
    stage_started = time.perf_counter()
    base_instructions = assistant_spec(assistant_name).system_prompt
    if system:
        base_instructions = f"{system}\n\n{base_instructions}"
    root_instructions = build_assistant_instructions(
        assistant_name,
        query,
        context_provider=context_provider,
        skill_provider=skill_provider,
        base_instructions=base_instructions,
        references=references,
    )
    handoff_instructions = {
        name: build_assistant_instructions(
            name,
            query,
            context_provider=context_provider,
            skill_provider=skill_provider,
            skills=skills,
            references=references,
        )
        for name in assistant_handoff_names(assistant_name)
    }
    if timing is not None:
        timing["instruction_assembly_ms"] = round(
            (time.perf_counter() - stage_started) * 1000, 3
        )
    return (
        root_instructions,
        handoff_instructions,
        references,
        skills,
    )


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
    (
        root_instructions,
        handoff_instructions,
        references,
        skills,
    ) = await _build_chat_instructions(
        messages,
        system,
        assistant_name=assistant_name,
        timing=timing,
    )
    for reference in references:
        yield stream_event(
            {
                "type": "context",
                "name": reference.heading or reference.context_file,
                "description": "Context chunk selected for this response.",
                "path": reference.path,
                "line": reference.line,
                "content": reference.content,
            }
        )
    for skill in skills:
        yield stream_event(
            {
                "type": "skill",
                "name": skill.name,
                "description": skill.description,
                "path": skill.path,
            }
        )
    reachable_tool_names = assistant_reachable_tool_names(assistant_name)
    setup_started = time.perf_counter()
    tools_by_name = {
        tool["name"]: tool for tool in list_tool_metadata(reachable_tool_names)
    }
    started_at = time.perf_counter()
    request_label = request_id or "unknown"
    reachable_groups = list_tool_group_metadata(reachable_tool_names)
    with development_trace(_agent_input(messages), enabled=load_config().chat.langfuse_tracing) as development, trace(
        "chat_tft",
        metadata={
            "assistant": assistant_name,
            "model": model_name,
            "message_count": str(len(messages)),
            "direct_tool_names": ",".join(
                assistant_tool_names(assistant_name)
            ),
            "tool_names": ",".join(reachable_tool_names),
            "tool_group_names": ",".join(
                (group.get("key") or group.get("name") or "")
                for group in reachable_groups
            ),
            "context_sources": ",".join(
                dict.fromkeys(snippet.path for snippet in references)
            ),
        },
    ) as chat_trace:
        trace_label = chat_trace.trace_id
        yield stream_event(
            {"type": "trace", "name": chat_trace.name, "trace_id": trace_label}
        )
        agent = create_assistant(
            assistant_name,
            instructions=root_instructions,
            model=model,
            instructions_by_name=handoff_instructions,
        )
        evidence_store = EvidenceStore()
        result = Runner.run_streamed(
            agent,
            input=_agent_input(messages),
            context=evidence_store,
            max_turns=max_tool_rounds + 1,
        )
        if timing is not None:
            timing["agent_setup_ms"] = round(
                (time.perf_counter() - setup_started) * 1000, 3
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
            async for chunk in stream_agent_events(
                result,
                tools_by_name=tools_by_name,
                request_id=request_label,
                trace_id=trace_label,
                evidence_store=evidence_store,
                on_model_event=mark_model_event,
                on_text_delta=mark_text_delta,
            ):
                yield chunk
        except MaxTurnsExceeded as e:
            logger.warning(
                "chat tool limit reached; generating tool-free response request_id=%s trace_id=%s elapsed_ms=%.1f",
                request_label,
                trace_label,
                (time.perf_counter() - started_at) * 1000,
            )
            final_agent = Agent(
                name=(
                    "chat_tft_final_response"
                    if assistant_name == CHAT_ASSISTANT_NAME
                    else f"{assistant_name}_final_response"
                ),
                instructions=root_instructions,
                model=model,
                model_settings=assistant_spec(assistant_name).model_settings(),
                tools=[],
                handoffs=[],
            )
            run_data = getattr(e, "run_data", None)
            new_items = getattr(run_data, "new_items", None)
            replay_items = run_items_to_input_items(new_items) if new_items else []
            stop_prompt = (
                SPECS_DIR / CHAT_ASSISTANT_NAME / "tool-loop-stop.md"
            ).read_text(encoding="utf-8").strip()
            final_result = Runner.run_streamed(
                final_agent,
                input=[
                    *_agent_input(messages),
                    *replay_items,
                    {"role": "user", "content": stop_prompt},
                ],
                max_turns=1,
                context=evidence_store,
            )
            async for chunk in stream_agent_events(
                final_result,
                tools_by_name={},
                request_id=request_label,
                trace_id=trace_label,
                evidence_store=evidence_store,
                on_model_event=mark_model_event,
                on_text_delta=mark_text_delta,
            ):
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
        assistant_spec(assistant_name)
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
    tool_names = assistant_reachable_tool_names(CHAT_ASSISTANT_NAME)
    tools = list_tool_metadata(tool_names)
    return {
        "composition_workbench": config.chat.composition_workbench,
        "flowchart_source": config.chat.flowchart_source,
        "default_assistant": CHAT_ASSISTANT_NAME,
        "assistants": list_assistants(),
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
