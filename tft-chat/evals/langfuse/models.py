"""Validated browser-run settings and durable evaluation job state."""
from __future__ import annotations

import json
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class PromptReference(BaseModel):
    """A UI-selected prompt version or label resolved before an experiment."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)
    label: str | None = None

    @model_validator(mode="after")
    def validate_selector(self) -> "PromptReference":
        """Reject ambiguous version/label selections before content is fetched."""
        if self.version is not None and self.label is not None:
            raise ValueError("Choose a prompt version or label, not both")
        return self


class Variant(BaseModel):
    """One named model and prompt configuration shown as an experiment."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="baseline", min_length=1, max_length=100)
    model: str | None = None
    prompts: dict[str, PromptReference] = Field(default_factory=dict)


class RunConfig(BaseModel):
    """Native Custom Experiment JSON settings accepted by the local service."""

    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["run", "replay", "export"] = "run"
    assistant: str | None = None
    cases: list[str] = Field(default_factory=list)
    variants: list[Variant] = Field(default_factory=lambda: [Variant()], min_length=1, max_length=10)
    dataset_version: str | None = None
    concurrency: int = Field(default=4, ge=1, le=4)
    repetitions: int = Field(default=1, ge=1, le=20)
    selection_live: bool = False
    data_snapshot_label: str | None = None
    snapshot: str | None = None

    @model_validator(mode="after")
    def validate_identity(self) -> "RunConfig":
        """Keep variant names unique and require a content hash for replay."""
        names = [variant.name for variant in self.variants]
        if len(names) != len(set(names)):
            raise ValueError("Variant names must be unique")
        if len(self.cases) != len(set(self.cases)):
            raise ValueError("Case selections must be unique")
        if self.action == "replay" and not self.snapshot:
            raise ValueError("Replay requires a snapshot ID")
        return self


class ExperimentTrigger(BaseModel):
    """Dataset identity and settings delivered by Langfuse's native webhook."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    project_id: str | None = Field(default=None, alias="projectId")
    dataset_id: str | None = Field(default=None, alias="datasetId")
    dataset_name: str = Field(alias="datasetName", min_length=1)
    config: RunConfig = Field(default_factory=RunConfig)

    @model_validator(mode="before")
    @classmethod
    def normalize_native_payload(cls, value: Any) -> Any:
        """Decode the pinned native UI's JSON-string payload field."""
        if isinstance(value, dict) and "payload" in value:
            value = dict(value)
            payload = value.pop("payload")
            if "config" in value:
                raise ValueError("Specify payload or config, not both")
            value["config"] = json.loads(payload) if isinstance(payload, str) else payload
        return value


class PlaygroundMessage(BaseModel):
    """Text-only conversation entry accepted by the backend Playground adapter."""

    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "developer", "user", "assistant"]
    content: str | list[dict[str, Any]]


class PlaygroundRequest(BaseModel):
    """Supported completion controls; reject knobs the backend cannot honor."""

    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[PlaygroundMessage] = Field(min_length=1, max_length=100)
    stream: bool = False
    stream_options: dict[str, Any] | None = None
    n: Literal[1] = 1
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1)
    max_completion_tokens: int | None = Field(default=None, ge=1)
    frequency_penalty: float | None = Field(default=None, ge=-2, le=2)
    presence_penalty: float | None = Field(default=None, ge=-2, le=2)
    tools: list[Any] | None = None
    tool_choice: str | None = None

    @model_validator(mode="after")
    def validate_backend_controls(self) -> "PlaygroundRequest":
        """Keep registered tools authoritative and token limits unambiguous."""
        if self.tools or self.tool_choice not in (None, "auto"):
            raise ValueError("ChatTFT supplies its own tools; remove Playground tool definitions and tool choice")
        if self.max_tokens is not None and self.max_completion_tokens is not None:
            raise ValueError("Choose max_tokens or max_completion_tokens, not both")
        return self
