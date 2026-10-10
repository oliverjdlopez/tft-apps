"""Typed browser contracts for the assistant draft lifecycle."""
from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RevisionRequest(BaseModel):
    """Expected draft and active identities for an optimistic mutation."""
    model_config = ConfigDict(extra='forbid')
    expected_draft: str | None = None
    expected_active: str = Field(min_length=64, max_length=64)
    expected_source: str = Field(min_length=64, max_length=64)


class SaveRequest(RevisionRequest):
    """Complete editable file contents, including optional file removal."""
    files: dict[str, str] = Field(max_length=3)
    provenance: dict[str, Any] | None = None


class TrialRequest(RevisionRequest):
    """One saved draft question executed with bounded playground limits."""
    question: str = Field(min_length=1, max_length=100_000)


class ExperimentRequest(RevisionRequest):
    """A persistent submission key and registered dataset selection."""
    submission_id: str = Field(min_length=16, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    dataset: str = Field(min_length=1)
    cases: list[str] = Field(default_factory=list, max_length=10_000)
    repetitions: int = Field(default=1, ge=1, le=20)


class RestoreRequest(RevisionRequest):
    """Restore an immutable historical revision into a new editable draft."""
    revision: str


class ImportRequest(RevisionRequest):
    """Import resolved text from an owned concrete Langfuse prompt version."""
    prompt: str
    version: int = Field(ge=1)


class ValidationResult(BaseModel):
    """Whole-graph validation with a derived editable configuration summary."""
    valid: bool
    errors: list[str]
    graph_hash: str | None = None
    configuration: dict[str, Any] | None = None


class DraftRevision(BaseModel):
    """Immutable saved contents and the source/runtime identities they began from."""
    id: str
    assistant: str
    created: float
    files: dict[str, str]
    content_hash: str
    base_active: str
    base_source: str
    validation: ValidationResult
    provenance: dict[str, Any] | None = None


class ActiveDefinitions(BaseModel):
    """Cached runtime definitions, distinct from externally modified source files."""
    hash: str
    files: dict[str, str]
    instructions: str
    configuration: dict[str, Any]


class RunReceipt(BaseModel):
    """Durable operation status tied to an exact assistant draft revision."""
    id: str
    assistant: str
    revision: str
    kind: str
    state: str
    created: float
    value: dict[str, Any]


class WorkspaceState(BaseModel):
    """Full assistant editor state returned after a read or lifecycle mutation."""
    name: str
    active: ActiveDefinitions
    source_hash: str
    source_changed: bool
    draft: DraftRevision | None
    validation: ValidationResult
    diff: dict[str, str]
    runs: list[RunReceipt]
    history: dict[str, Any]
    configuration: dict[str, Any] | None
