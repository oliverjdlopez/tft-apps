from __future__ import annotations

import pytest

from core.config import AppConfig, ModelConfig
from domain.constants import AnthropicModels, OpenAIModels
from domain.model_catalog import chat_model_spec, chat_model_specs


def test_chat_model_catalog_is_curated_and_default_first() -> None:
    config = AppConfig(
        models=ModelConfig(
            openai_model=OpenAIModels.LUNA.value,
            anthropic_model=AnthropicModels.SONNET.value,
        )
    )

    specs = chat_model_specs(config)

    assert specs[0].id == OpenAIModels.LUNA.value
    assert specs[0].is_default is True
    assert all(spec.id in spec.label for spec in specs)
    assert OpenAIModels.CODEX_LATEST.value not in {spec.id for spec in specs}
    assert OpenAIModels.NANO.value not in {spec.id for spec in specs}


def test_chat_model_catalog_accepts_trusted_configured_models() -> None:
    config = AppConfig(
        models=ModelConfig(
            openai_model="gpt-private-deployment",
            anthropic_model="claude-private-deployment",
        )
    )

    specs = chat_model_specs(config)

    assert specs[0].id == "gpt-private-deployment"
    assert all(spec.id in spec.label for spec in specs)
    assert chat_model_spec("claude-private-deployment", config).provider == "anthropic"


def test_chat_model_catalog_rejects_unexposed_models() -> None:
    with pytest.raises(KeyError):
        chat_model_spec(OpenAIModels.CODEX_LATEST.value, AppConfig())
