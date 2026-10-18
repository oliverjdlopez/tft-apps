"""Strict source and structured-output contracts for transcript tasks."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Nonblank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TaskModel(BaseModel):
    """Reject unexpected fields at model and HTTP application boundaries."""

    model_config = ConfigDict(extra="forbid", strict=True)


class TranscriptSource(TaskModel):
    """Identify a transcript without filesystem or external context."""

    transcription_task_id: Nonblank
    title: str | None = None
    language: str | None = None


class TranscriptSegment(TaskModel):
    """Retain original speech timing and stable source-array identity."""

    id: Nonblank
    start: float = Field(ge=0, allow_inf_nan=False)
    end: float = Field(ge=0, allow_inf_nan=False)
    text: str

    @model_validator(mode="after")
    def ordered_end(self):
        """Reject negative-duration speech without altering gaps or overlaps."""
        if self.end < self.start:
            raise ValueError("Segment end precedes start")
        return self


class KeyMomentsInput(TaskModel):
    """Accept only media-relative seconds and an ordered original segment array."""

    schema_version: Literal[1]
    source: TranscriptSource
    time_unit: Literal["seconds"]
    time_origin: Literal["media_start"]
    segments: list[TranscriptSegment] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_segments(self):
        """Reject duplicate identities, reordered starts, and empty speech."""
        ids = [s.id for s in self.segments]
        if len(set(ids)) != len(ids):
            raise ValueError("Segment IDs must be unique")
        if any(a.start > b.start for a, b in zip(self.segments, self.segments[1:])):
            raise ValueError("Segment starts must be nondecreasing")
        if not any(s.text.strip() for s in self.segments):
            raise ValueError("No speech was detected")
        return self


class EvidenceRange(TaskModel):
    """Refer to an inclusive slice by original segment IDs."""

    start_segment_id: Nonblank
    end_segment_id: Nonblank


class KeyMoment(TaskModel):
    """Describe significance grounded in one or more supporting passages."""

    title: Nonblank
    explanation: Nonblank
    evidence: list[EvidenceRange] = Field(min_length=1)


class KeyMomentsOutput(TaskModel):
    """Allow abstention when the supplied speech establishes no critical moments."""

    moments: list[KeyMoment]
