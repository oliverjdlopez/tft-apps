"""Prepared invocation state and machine-consumed assistant output contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    from agents import Agent
    from domain.runtime.models import AssistantRunContext
    from domain.runtime.activity import ActivityRunHooks


@dataclass
class AssistantInvocation:
    """Hold a fresh prepared run for consumers that own SDK execution.

    Consumers pass agent, input, context, and hooks to the SDK runner. Optional
    instruction recording is invocation-local and retains failed-run provenance.
    """

    agent: Agent[Any]
    input: str | list[dict[str, str]]
    context: AssistantRunContext
    hooks: ActivityRunHooks
    instructions: dict[str, str] = field(default_factory=dict)
    model_settings: dict[str, dict[str, Any]] = field(default_factory=dict)


__all__ = ["AssistantInvocation"]
