"""VOD-owned catalogue, request, run, and structured response contracts."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class StrictModel(BaseModel):
    """Forbid unrecognized fields received across application boundaries."""

    model_config = ConfigDict(extra="forbid")


class StartRequest(StrictModel):
    """Require an explicit user rerun to create another attempt after success."""

    rerun: bool = False


class TaskDefinition(StrictModel):
    """Describe an explicitly supported, versioned transcript action."""

    name: str
    label: str
    description: str
    version: int
    requires_timestamps: bool
    output_kind: Literal["markdown", "key_moments"]


TASKS = {
    item.name: item for item in [
        TaskDefinition(name="transcription_pipeline", label="Distill transcript", description="Distill source-grounded Markdown notes.", version=1, requires_timestamps=False, output_kind="markdown"),
        TaskDefinition(name="find_key_moments", label="Find key moments", description="Find consequential passages grounded in the speaker's words.", version=1, requires_timestamps=True, output_kind="key_moments"),
    ]
}


class Evidence(StrictModel):
    """Accept only source IDs from the upstream model output."""

    start_segment_id: Nonblank
    end_segment_id: Nonblank


class Moment(StrictModel):
    """Validate an upstream passage before resolving playback data locally."""

    title: Nonblank
    explanation: Nonblank
    evidence: list[Evidence] = Field(min_length=1)


class KeyMoments(StrictModel):
    """Permit a valid empty result without manufacturing moments."""

    moments: list[Moment]


class TaskRun(StrictModel):
    """Represent a persisted attempt; successful outputs stay readable offline."""

    id: str
    transcription_task_id: str
    task_name: str
    task_version: int
    transcript_hash: str
    status: Literal["queued", "running", "completed", "failed"]
    output: str | dict | None
    error_code: str | None
    error: str | None
    created_at: str
    updated_at: str
