"""Assistant definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.constants import OpenAIModels, ReasoningEfforts


@dataclass(frozen=True)
class AssistantSpec:
    """Immutable configuration used to construct one application assistant."""

    name: str
    description: str
    handoff_description: str
    system_prompt: str
    task_prompt: str
    path: str
    model: OpenAIModels | None = None
    reasoning: ReasoningEfforts | None = ReasoningEfforts.MEDIUM
    include_all_tools: bool = False
    tool_group_keys: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    handoff_names: tuple[str, ...] = ()
    repository_context: bool = False
    # Omission permits every package; an empty tuple explicitly denies access.
    skill_names: tuple[str, ...] | None = None
    playbook_names: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        """Apply the same invariants to files, captures, and direct construction."""
        self.validate_invariants()

    def validate_invariants(self) -> None:
        """Validate runtime values and normalize enums and immutable name lists.

        Empty descriptions and prompts are valid, including cleared experiments.
        Permission flags must be real booleans; a truthy string must never grant
        access. None and an empty allowlist retain their distinct meanings.

        Raises:
            ValueError: If a field cannot represent a usable runtime definition.
        """
        for field in ("name", "description", "handoff_description", "system_prompt", "task_prompt", "path"):
            value = getattr(self, field)
            if not isinstance(value, str):
                raise ValueError(f"{field} must be text")
            if field == "name" and not value.strip():
                raise ValueError(f"{field} must be nonempty")
        for field in ("include_all_tools", "repository_context"):
            if not isinstance(getattr(self, field), bool):
                raise ValueError(f"{field} must be a boolean")
        for field in ("tool_group_keys", "tool_names", "handoff_names", "skill_names", "playbook_names"):
            value = getattr(self, field)
            if value is None and field in {"skill_names", "playbook_names"}:
                continue
            if not isinstance(value, (list, tuple)) or any(
                not isinstance(name, str) or not name.strip() for name in value
            ):
                raise ValueError(f"{field} must be a sequence of nonempty names")
            object.__setattr__(self, field, tuple(dict.fromkeys(name.strip() for name in value)))
        for field, enum in (("model", OpenAIModels), ("reasoning", ReasoningEfforts)):
            value = getattr(self, field)
            if value is not None:
                try:
                    object.__setattr__(self, field, enum(value.strip() if isinstance(value, str) else value))
                except (TypeError, ValueError):
                    raise ValueError(f"{field} must be a valid {enum.__name__} value") from None

    def resolved_model(self) -> str:
        """Return the pinned model or the application's configured default."""
        if self.model is not None:
            return self.model.value
        from core.config import load_config

        return load_config().models.openai_model

    def model_settings(self) -> Any:
        """Build SDK model settings from the declared reasoning effort."""
        from agents import ModelSettings
        from openai.types.shared.reasoning import Reasoning

        reasoning = None
        if self.reasoning is not None:
            reasoning = Reasoning(effort=self.reasoning.value)
        return ModelSettings(reasoning=reasoning)


__all__ = ["AssistantSpec"]
