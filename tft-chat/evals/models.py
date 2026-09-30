"""Observable execution models shared by evaluation runners and assertions."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class ToolCall:
    """One tool invocation observed during a run."""

    name: str
    arguments: str = ""
    agent: str | None = None
    call_id: str | None = None
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize this observation for evaluation assertions and reports."""
        return {
            "name": self.name,
            "arguments": self.arguments,
            "agent": self.agent,
            "call_id": self.call_id,
            "output": self.output,
        }


@dataclass(frozen=True)
class Handoff:
    """One agent-to-agent handoff observed during a run."""

    source: str
    target: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize this observation for evaluation assertions and reports."""
        return {"source": self.source, "target": self.target}


@dataclass(frozen=True)
class TraceEvent:
    """One ordered tool or handoff event observed during a run."""

    type: str
    agent: str | None = None
    tool: str | None = None
    source: str | None = None
    target: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event for eval reports and debugging."""
        return {
            "type": self.type,
            "agent": self.agent,
            "tool": self.tool,
            "source": self.source,
            "target": self.target,
        }


    def summary(self) -> str:
        """Render this event in the evidence supplied to rubric graders."""
        if self.type == "handoff":
            return f"{self.source or '?'} -> {self.target or '?'}"
        if self.type == "tool_call":
            return f"{self.agent or '?'} called {self.tool or '?'}"
        return self.type


@dataclass(frozen=True)
class EvalTrace:
    """What the assistant actually did while producing an output."""

    trace_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    handoffs: list[Handoff] = field(default_factory=list)
    final_agent: str | None = None
    turns: int | None = None
    events: list[TraceEvent] = field(default_factory=list)

    @property
    def tool_names(self) -> list[str]:
        """Return the observable tool names used by eval assertions and reports."""
        return [call.name for call in self.tool_calls]

    @property
    def handoff_targets(self) -> list[str]:
        """Return the observable handoff targets used by eval assertions and reports."""
        return [handoff.target for handoff in self.handoffs]

    def tool_call_count(self, name: str) -> int:
        """Return the observable tool call count used by eval assertions and reports."""
        return sum(1 for call in self.tool_calls if call.name == name)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this observation for evaluation assertions and reports."""
        return {
            "trace_id": self.trace_id,
            "tool_calls": [call.to_dict() for call in self.tool_calls],
            "handoffs": [handoff.to_dict() for handoff in self.handoffs],
            "final_agent": self.final_agent,
            "turns": self.turns,
            "events": [event.to_dict() for event in self.events],
        }

    def summary(self) -> str:
        """Compact single-paragraph description for judge prompts and reports."""
        parts: list[str] = []
        if self.tool_calls:
            counts: dict[str, int] = {}
            for call in self.tool_calls:
                label = call.name if call.agent is None else f"{call.name}@{call.agent}"
                counts[label] = counts.get(label, 0) + 1
            rendered = ", ".join(
                name if count == 1 else f"{name} x{count}" for name, count in counts.items()
            )
            parts.append(f"tools called: {rendered}")
        else:
            parts.append("tools called: none")
        if self.handoffs:
            path = "; ".join(f"{handoff.source} -> {handoff.target}" for handoff in self.handoffs)
            parts.append(f"handoffs: {path}")
        else:
            parts.append("handoffs: none")
        if self.events:
            ordered = "; ".join(event.summary() for event in self.events)
            parts.append(f"ordered events: {ordered}")
        if self.final_agent:
            parts.append(f"final agent: {self.final_agent}")
        if self.turns is not None:
            parts.append(f"model turns: {self.turns}")
        return "; ".join(parts)


@dataclass(frozen=True)
class TraceCheckResult:
    """Result of one deterministic trace or output check."""

    name: str
    check_type: str
    score: float
    threshold: float
    passed: bool
    weight: float = 1.0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize this observation for evaluation assertions and reports."""
        return {
            "name": self.name,
            "type": self.check_type,
            "score": self.score,
            "threshold": self.threshold,
            "passed": self.passed,
            "weight": self.weight,
            "message": self.message,
        }



@dataclass(frozen=True)
class EvalSuite:
    """Local evaluation suite metadata used by validation and spec discovery."""

    name: str
    assistant: str
    execution: str
    tests: list[dict[str, Any]]
    provider: dict[str, Any]
