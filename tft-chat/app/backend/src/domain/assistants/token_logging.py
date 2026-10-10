"""Write lightweight token-count diagnostics for assistant prompts."""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from agents import Agent
from agents.handoffs import Handoff, handoff


litellm_spec = importlib.util.find_spec("litellm")
if litellm_spec is None or litellm_spec.origin is None:
    raise RuntimeError("the configured Agents SDK LiteLLM dependency is unavailable")
os.environ.setdefault(
    "TIKTOKEN_CACHE_DIR",
    str(Path(litellm_spec.origin).parent / "litellm_core_utils" / "tokenizers"),
)

import tiktoken


offline_encoding = tiktoken.get_encoding("o200k_base")


# Containers expose a writable state home while their application code is immutable.
PROMPT_TOKEN_LOG_PATH = (
    Path(os.environ["XDG_STATE_HOME"]) / "tft-chat" / "prompt_tokens.log"
    if os.environ.get("XDG_STATE_HOME") else Path(__file__).with_name("prompt_tokens.log")
)
if os.environ.get("XDG_STATE_HOME"):
    PROMPT_TOKEN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
prompt_token_logger = logging.getLogger("tft.assistants.prompt_tokens")
prompt_token_logger.setLevel(logging.INFO)
prompt_token_logger.propagate = False
if not any(
    isinstance(handler, RotatingFileHandler)
    and Path(handler.baseFilename) == PROMPT_TOKEN_LOG_PATH
    for handler in prompt_token_logger.handlers
):
    prompt_token_handler = RotatingFileHandler(
        PROMPT_TOKEN_LOG_PATH,
        maxBytes=1024 * 1024,
        backupCount=1,
        encoding="utf-8",
        delay=True,
    )
    prompt_token_handler.setLevel(logging.INFO)
    prompt_token_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    prompt_token_logger.addHandler(prompt_token_handler)


def _encoding_name(model: str) -> str:
    """Return the offline tokenizer name used for a configured model.

    Args:
        model: Configured model name.

    Returns:
        The bundled tokenizer name.
    """
    del model
    return offline_encoding.name


def count_tokens(text: str, *, model: str) -> int:
    """Count tokens in text without retaining or logging its contents.

    Args:
        text: Text to tokenize.
        model: Configured model name used to choose an encoding.

    Returns:
        Number of encoded tokens.
    """
    del model
    return len(offline_encoding.encode(text)) if text else 0


def _definition_tokens(definitions: list[dict[str, Any]], *, model: str) -> int:
    """Count tokens in serialized model-facing definitions.

    Args:
        definitions: Tool or handoff definitions exposed to the model.
        model: Configured model name used to choose an encoding.

    Returns:
        Number of tokens in the compact JSON representation.
    """
    if not definitions:
        return 0
    serialized = json.dumps(
        definitions,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return count_tokens(serialized, model=model)


def _model_name(agent: Agent[Any]) -> str:
    """Return a stable configured model name for an SDK agent.

    Args:
        agent: SDK agent whose model should be identified.

    Returns:
        Model name without object representations or credentials.
    """
    if isinstance(agent.model, str):
        return agent.model
    configured_name = getattr(agent.model, "model", None)
    return (
        configured_name
        if isinstance(configured_name, str)
        else type(agent.model).__name__
    )


def _tool_definitions(agent: Agent[Any]) -> list[dict[str, Any]]:
    """Return the model-facing portions of an agent's function tools.

    Args:
        agent: SDK agent whose direct tools should be summarized.

    Returns:
        Serializable tool definitions without executable callbacks.
    """
    return [
        {
            "name": getattr(tool, "name", type(tool).__name__),
            "description": getattr(tool, "description", ""),
            "parameters": getattr(tool, "params_json_schema", {}),
            "strict": getattr(tool, "strict_json_schema", False),
            "type": "function",
        }
        for tool in agent.tools
    ]


def _handoff_definitions(agent: Agent[Any]) -> list[dict[str, Any]]:
    """Return the model-facing portions of an agent's handoffs.

    Args:
        agent: SDK agent whose handoffs should be summarized.

    Returns:
        Serializable handoff tool definitions.
    """
    definitions: list[dict[str, Any]] = []
    for target in agent.handoffs:
        resolved = target if isinstance(target, Handoff) else handoff(target)
        definitions.append(
            {
                "name": resolved.tool_name,
                "description": resolved.tool_description,
                "parameters": resolved.input_json_schema,
                "strict": resolved.strict_json_schema,
                "type": "function",
            }
        )
    return definitions


def log_instruction_parts(
    *,
    assistant_name: str,
    model: str,
    base_instructions: str,
    task_prompt: str,
    repository_context: str,
    skills: str,
    assembled_instructions: str,
    context_names: list[str],
    skill_names: list[str],
) -> None:
    """Log token counts for the sections assembled by prompt providers.

    Args:
        assistant_name: Registered assistant name.
        model: Configured model name used to choose an encoding.
        base_instructions: Durable assistant instructions.
        task_prompt: Optional task input wrapper.
        repository_context: Rendered selected factual context.
        skills: Rendered selected skill instructions.
        assembled_instructions: Final joined instruction string.
        context_names: Selected context source names.
        skill_names: Selected skill names.
    """
    payload = {
        "event": "instruction_parts",
        "assistant": assistant_name,
        "model": model,
        "encoding": _encoding_name(model),
        "tokens": {
            "base_instructions": count_tokens(base_instructions, model=model),
            "task_prompt": count_tokens(task_prompt, model=model),
            "repository_context": count_tokens(repository_context, model=model),
            "skills": count_tokens(skills, model=model),
            "assembled_instructions": count_tokens(
                assembled_instructions, model=model
            ),
        },
        "context_sources": context_names,
        "skills": skill_names,
    }
    prompt_token_logger.info(json.dumps(payload, separators=(",", ":")))


def log_agent_graph(agent: Agent[Any], *, task_prompt: str) -> None:
    """Log instruction and tool-definition counts for a fresh agent graph.

    Args:
        agent: Root SDK agent with its fresh handoff graph.
        task_prompt: Optional task wrapper belonging to the root assistant.
    """
    summaries: list[dict[str, Any]] = []
    seen: set[int] = set()

    def visit(candidate: Agent[Any], *, root: bool) -> None:
        """Collect one agent and recursively visit direct handoff agents.

        Args:
            candidate: Agent currently being summarized.
            root: Whether this is the root agent in the graph.
        """
        if id(candidate) in seen:
            return
        seen.add(id(candidate))
        model = _model_name(candidate)
        dynamic_instructions = callable(candidate.instructions)
        instructions = (
            candidate.instructions if isinstance(candidate.instructions, str) else ""
        )
        tool_definitions = _tool_definitions(candidate)
        handoff_definitions = _handoff_definitions(candidate)
        task_tokens = count_tokens(task_prompt, model=model) if root else 0
        # Dynamic callbacks need a run context and must not be executed just for
        # diagnostics. Their instruction count remains unresolved at construction.
        instruction_tokens = (
            None if dynamic_instructions else count_tokens(instructions, model=model)
        )
        tool_tokens = _definition_tokens(tool_definitions, model=model)
        handoff_tokens = _definition_tokens(handoff_definitions, model=model)
        summaries.append(
            {
                "assistant": candidate.name,
                "model": model,
                "encoding": _encoding_name(model),
                "instructions_kind": "dynamic" if dynamic_instructions else "static",
                "tokens": {
                    "instructions": instruction_tokens,
                    "task_prompt": task_tokens,
                    "tools": tool_tokens,
                    "handoffs": handoff_tokens,
                    "estimated_static_total": (
                        None
                        if instruction_tokens is None
                        else instruction_tokens + task_tokens + tool_tokens + handoff_tokens
                    ),
                },
                "tool_count": len(tool_definitions),
                "handoff_count": len(handoff_definitions),
            }
        )
        for target in candidate.handoffs:
            if isinstance(target, Agent):
                visit(target, root=False)

    visit(agent, root=True)
    prompt_token_logger.info(
        json.dumps(
            {
                "event": "agent_graph",
                "root_assistant": agent.name,
                "agents": summaries,
            },
            separators=(",", ":"),
        )
    )


__all__ = [
    "PROMPT_TOKEN_LOG_PATH",
    "count_tokens",
    "log_agent_graph",
    "log_instruction_parts",
]
