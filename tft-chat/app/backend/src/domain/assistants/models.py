"""Structured output contracts for assistants with machine-consumed results."""

from __future__ import annotations

from typing import Annotated, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel


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


class CompactTranscriptOutput(RootModel[str]):
    """A compact transcript represented as one continuous text block."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TranscriptReplacement(_StrictModel):
    id: int
    text: str


class TranscriptMerge(_StrictModel):
    merge: list[int] = Field(min_length=1)
    text: str


class TranscriptDeletion(_StrictModel):
    delete: list[int] = Field(min_length=1)


TranscriptEdit = Annotated[
    Union[TranscriptReplacement, TranscriptMerge, TranscriptDeletion],
    Field(union_mode="smart"),
]


class CleanTranscriptOutput(_StrictModel):
    """Edits to apply to the source transcript."""

    edits: list[TranscriptEdit]


__all__ = [
    "CandidateIdSelection",
    "CleanTranscriptOutput",
    "CompactTranscriptOutput",
    "ContextSelection",
    "ContextSelectionNeed",
]
