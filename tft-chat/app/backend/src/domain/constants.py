from enum import StrEnum

class ReasoningEfforts(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"


class OpenAIModels(StrEnum):
    NANO = "gpt-5.4-nano"
    MINI = "gpt-5.4-mini"
    DEFAULT = "gpt-5.4"
    TERRA = "gpt-5.6-terra"
    LUNA = "gpt-6-luna"
    SOL = "gpt-6-sol"
    CODEX_LATEST = "gpt-5.3-codex"
    LATEST = "gpt-6-astra"
    PRO = "gpt-5.5-pro"


class AnthropicModels(StrEnum):
    HAIKU = "claude-haiku-4-5-20251001"
    SONNET = "claude-sonnet-5"
    OPUS = "claude-opus-4-8"
    FABLE = "claude-fable-5"
