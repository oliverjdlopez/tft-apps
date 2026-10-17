"""Record model-facing instruction and model metadata for development runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents import Agent, RunContextWrapper

from domain.assistants.models import AssistantInvocation
from devtools.assistants.diagnostics import agent_model_name


@dataclass
class InvocationRecording:
    """Retain development provenance independently of a runtime invocation."""

    instructions: dict[str, str] = field(default_factory=dict)
    model_settings: dict[str, dict[str, Any]] = field(default_factory=dict)


def record_invocation(invocation: AssistantInvocation) -> InvocationRecording:
    """Attach transparent instruction recording to a prepared assistant graph."""
    recording = InvocationRecording()
    seen: set[int] = set()

    def visit(agent: Agent[Any]) -> None:
        """Wrap each graph object once while retaining its instruction callback."""
        if id(agent) in seen:
            return
        seen.add(id(agent))
        recording.model_settings[agent.name] = {
            "model": agent_model_name(agent),
            "settings": agent.model_settings.to_json_dict(),
        }
        callback = agent.instructions

        def render(wrapper: RunContextWrapper[Any], target: Agent[Any]) -> str:
            """Record the original callback result without changing it."""
            text = callback(wrapper, target) if callable(callback) else callback
            recording.instructions[target.name] = text
            return text

        agent.instructions = render
        for child in agent.handoffs:
            visit(child)

    visit(invocation.agent)
    return recording

