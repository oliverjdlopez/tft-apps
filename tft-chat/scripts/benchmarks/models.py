"""Data models shared by the development database benchmark runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


BenchmarkTier = Literal["light", "heavy"]
BenchmarkPhase = Literal["discovery", "warmup", "timed", "profile"]
ExpectedResultKind = Literal["table", "resolution", "comparison"]


@dataclass(frozen=True)
class WorkloadDefinition:
    """Describe a benchmark workload before representative names are known.

    Args:
        name: Stable identifier used in logs and artifact filenames.
        tier: ``light`` or ``heavy`` workload category.
        tool_name: Registered database tool exercised by the workload.
        description: Human-readable purpose shown by ``--list``.
        expected_kind: Structured result family expected from the tool.
        group_by: Expected table grain when the result is tabular.
        prerequisites: Preconditions required for meaningful output.
    """

    name: str
    tier: BenchmarkTier
    tool_name: str
    description: str
    expected_kind: ExpectedResultKind = "table"
    group_by: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()


@dataclass(frozen=True)
class BenchmarkCase:
    """Represent one fully bound database-tool invocation workload.

    Args:
        name: Stable workload identifier.
        tier: Workload category.
        tool_name: Registered database tool to invoke.
        arguments: JSON-compatible tool arguments for the selected database.
        description: Human-readable workload description.
        expected_kind: Structured result family expected from the tool.
        group_by: Expected table grain when the result is tabular.
        prerequisites: Preconditions required for meaningful output.
    """

    name: str
    tier: BenchmarkTier
    tool_name: str
    arguments: dict[str, Any]
    description: str
    expected_kind: ExpectedResultKind = "table"
    group_by: tuple[str, ...] = ()
    prerequisites: tuple[str, ...] = ()


@dataclass
class InvocationRecord:
    """Record one benchmark invocation without retaining its full result.

    Args:
        case_name: Workload identifier.
        phase: Discovery, warmup, timed, or profile phase.
        iteration: Zero-based iteration within the phase.
        call_id: Unique ID propagated to database diagnostics.
        elapsed_ms: End-to-end invocation duration.
        status: One of success, invalid_input, tool_error, invalid_result,
            timeout, insufficient_data, or exception.
        result_metadata: Bounded shape and count metadata from the result.
        database_timing: Internal timing fields emitted by ``run_db_tool``.
        error_type: Exception or tool-error type when the call failed.
        error: Bounded diagnostic text when the call failed.
        result: Optional in-memory result retained only for discovery.
    """

    case_name: str
    phase: BenchmarkPhase
    iteration: int
    call_id: str
    elapsed_ms: float
    status: Literal[
        "success",
        "invalid_input",
        "tool_error",
        "invalid_result",
        "timeout",
        "insufficient_data",
        "exception",
    ]
    result_metadata: dict[str, Any] = field(default_factory=dict)
    database_timing: dict[str, Any] = field(default_factory=dict)
    error_type: str | None = None
    error: str | None = None
    result: Any = field(default=None, repr=False)


@dataclass(frozen=True)
class ProfileArtifact:
    """Describe the files produced by one worker-thread profile run.

    Args:
        stats_path: Path to the binary ``pstats`` artifact.
        text_path: Path to the readable cumulative-time report.
        status: Profile status.
        error: Bounded profile error, if profile generation failed.
    """

    stats_path: str
    text_path: str
    status: str
    error: str | None = None


@dataclass
class CaseReport:
    """Collect timed records and profile output for one benchmark case.

    Args:
        case: Fully bound workload definition.
        records: Warmup, timed, and profile invocation records.
        profile: Optional profile artifact for the case.
        status: Aggregate case status.
        error: Bounded case-level error, if execution could not continue.
    """

    case: BenchmarkCase
    records: list[InvocationRecord] = field(default_factory=list)
    profile: ProfileArtifact | None = None
    status: str = "success"
    error: str | None = None
