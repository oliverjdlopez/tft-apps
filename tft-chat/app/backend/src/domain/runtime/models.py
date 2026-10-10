"""Dependency-neutral state for one logical assistant invocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from domain.providers.models import (
        ContextProvider,
        ContextSnippet,
        SkillDefinition,
        SkillProvider,
    )
    from domain.tools.evidence.models import EvidenceStore


@dataclass(frozen=True)
class RuntimeSettings:
    """Hold explicit settings shared by a request's agents and tools."""

    request_id: str
    set_number: int | None
    root_assistant: str
    surface: str = "chat"
    system: str | None = None


@dataclass(frozen=True)
class PreparedResources:
    """Hold the selector query and resources selected once for an invocation."""

    query: str = ""
    references: tuple[ContextSnippet, ...] = ()
    skills: tuple[SkillDefinition, ...] = ()


@dataclass
class ToolActivity:
    """Track one tool execution independently of concurrent or repeated calls."""

    call_id: str
    name: str
    agent_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    started_at: float | None = None
    ended_at: float | None = None
    status: Literal["running", "completed", "failed", "cancelled"] = "running"


@dataclass
class ActivityState:
    """Retain invocation-local lifecycle records without emitting browser events."""

    calls: dict[str, ToolActivity] = field(default_factory=dict)
    handoffs: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class AssistantRunContext:
    """Supply application dependencies and state to SDK callbacks and tools.

    The SDK does not expose this object to the model. Consumers deliberately
    render permitted instructions, tool results, or browser events instead.
    Type-only imports keep this contract independent of registry initialization.
    Provider overrides apply to the whole invocation; None uses agent defaults.
    """

    runtime: RuntimeSettings
    resources: PreparedResources = field(default_factory=PreparedResources)
    context_provider: ContextProvider | None = None
    skill_provider: SkillProvider | None = None
    evidence: EvidenceStore | None = None
    activity: ActivityState = field(default_factory=ActivityState)
    timing: dict[str, Any] | None = None
