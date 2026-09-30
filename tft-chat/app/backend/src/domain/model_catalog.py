"""Curated chat-model metadata and provider resolution.

The enum modules contain every model identifier used by the repository.  This
catalog is deliberately smaller: it is the product surface offered to ChatTFT
users, so coding-only and superseded variants do not become accidental choices.
Configured defaults are trusted operator input and are added when necessary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from core.config import AppConfig, load_config
from domain.constants import AnthropicModels, OpenAIModels


ModelProvider = Literal["openai", "anthropic"]


@dataclass(frozen=True)
class ChatModelSpec:
    id: str
    provider: ModelProvider
    description: str
    tier: Literal["fast", "balanced", "quality"]
    is_default: bool = False

    @property
    def label(self) -> str:
        """Return a dropdown label that includes the exact API model ID."""
        provider_label = "OpenAI" if self.provider == "openai" else "Anthropic"
        return f"{provider_label} · {self.id}"


_BUILTIN_CHAT_MODELS: tuple[ChatModelSpec, ...] = (
    ChatModelSpec(
        id=OpenAIModels.LATEST.value,
        provider="openai",
        description="Highest-quality OpenAI option for multi-step analysis.",
        tier="quality",
    ),
    ChatModelSpec(
        id=OpenAIModels.SOL.value,
        provider="openai",
        description="High-quality OpenAI option for multi-step analysis.",
        tier="quality",
    ),
    ChatModelSpec(
        id=OpenAIModels.TERRA.value,
        provider="openai",
        description="Balanced OpenAI option for analysis quality and cost.",
        tier="balanced",
    ),
    ChatModelSpec(
        id=OpenAIModels.LUNA.value,
        provider="openai",
        description="Cost-sensitive OpenAI option that retains tool use.",
        tier="balanced",
    ),
    ChatModelSpec(
        id=OpenAIModels.DEFAULT.value,
        provider="openai",
        description="Previous-generation general-purpose reasoning model.",
        tier="balanced",
    ),
    ChatModelSpec(
        id=OpenAIModels.MINI.value,
        provider="openai",
        description="Fast, lower-cost option for simpler investigations.",
        tier="fast",
    ),
    ChatModelSpec(
        id=AnthropicModels.FABLE.value,
        provider="anthropic",
        description="Highest-capability Claude option for difficult investigations.",
        tier="quality",
    ),
    ChatModelSpec(
        id=AnthropicModels.OPUS.value,
        provider="anthropic",
        description="Deep-analysis Claude option for complex agentic work.",
        tier="quality",
    ),
    ChatModelSpec(
        id=AnthropicModels.SONNET.value,
        provider="anthropic",
        description="Balanced Claude option for speed and intelligence.",
        tier="balanced",
    ),
    ChatModelSpec(
        id=AnthropicModels.HAIKU.value,
        provider="anthropic",
        description="Fastest Claude option for lower-latency answers.",
        tier="fast",
    ),
)


def _configured_model(
    model_id: str,
    provider: ModelProvider,
) -> ChatModelSpec:
    return ChatModelSpec(
        id=model_id,
        provider=provider,
        description="Operator-configured model.",
        tier="balanced",
    )


def chat_model_specs(config: AppConfig | None = None) -> tuple[ChatModelSpec, ...]:
    """Return the curated chat models, with the configured OpenAI default first."""
    resolved_config = config or load_config()
    configured = (
        (resolved_config.models.openai_model, "openai"),
        (resolved_config.models.anthropic_model, "anthropic"),
    )

    by_id = {spec.id: spec for spec in _BUILTIN_CHAT_MODELS}
    for model_id, provider in configured:
        if model_id and model_id not in by_id:
            by_id[model_id] = _configured_model(model_id, provider)

    default_id = resolved_config.models.openai_model
    ordered_ids = [default_id, *(spec.id for spec in _BUILTIN_CHAT_MODELS)]
    if resolved_config.models.anthropic_model:
        ordered_ids.append(resolved_config.models.anthropic_model)

    result: list[ChatModelSpec] = []
    seen: set[str] = set()
    for model_id in ordered_ids:
        if not model_id or model_id in seen:
            continue
        result.append(replace(by_id[model_id], is_default=model_id == default_id))
        seen.add(model_id)
    return tuple(result)


def chat_model_spec(model_id: str, config: AppConfig | None = None) -> ChatModelSpec:
    """Resolve one model exposed by chat or reject it."""
    for spec in chat_model_specs(config):
        if spec.id == model_id:
            return spec
    raise KeyError(model_id)


__all__ = [
    "ChatModelSpec",
    "ModelProvider",
    "chat_model_spec",
    "chat_model_specs",
]
