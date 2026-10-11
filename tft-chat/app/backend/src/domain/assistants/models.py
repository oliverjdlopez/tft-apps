"""Prepared invocation state and machine-consumed assistant output contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, TYPE_CHECKING, Union

from pydantic import BaseModel, ConfigDict, Field, RootModel

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
    "AssistantInvocation",
    "CandidateIdSelection",
    "CleanTranscriptOutput",
    "CompactTranscriptOutput",
    "ContextSelection",
    "ContextSelectionNeed",
]
