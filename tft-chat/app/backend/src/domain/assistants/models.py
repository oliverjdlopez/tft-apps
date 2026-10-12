"""Prepared invocation state and machine-consumed assistant output contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

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


class ContextSelectionNeed(BaseModel):
    """Candidates that satisfy one distinct factual need in a request."""

    model_config = ConfigDict(extra="forbid")

    need: str
    part_ids: list[int]


class ContextSelection(BaseModel):
    """Coverage-aware context selection grouped by factual need."""

    model_config = ConfigDict(extra="forbid")

    selections: list[ContextSelectionNeed]


class CandidateIdSelection(BaseModel):
    """Candidate IDs ordered from most to least relevant."""

    model_config = ConfigDict(extra="forbid")

    selected_ids: list[int]


__all__ = [
    "AssistantInvocation",
    "CandidateIdSelection",
    "ContextSelection",
    "ContextSelectionNeed",
]
