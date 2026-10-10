from enum import StrEnum


class AssistantName(StrEnum):
    """Identify built-in assistants and named runtime/fixture agents.

    Values remain strings at JSON, SDK, CLI, and repository-spec boundaries.
    User-created specification names may still be supplied dynamically.
    """

    ANALYZE_TRANSCRIPT = "analyze_transcript"
    CHAT = "chat"
    CHAT_FINAL_RESPONSE = "chat_tft_final_response"
    CLEAN_TRANSCRIPT = "clean_transcript"
    COMPACT_TRANSCRIPT = "compact_transcript"
    COMP_EXPERT = "comp_expert"
    CONTEXT_SELECTOR = "context_selector"
    DATA_ANALYST = "data_analyst"
    DUMMY_ASSISTANT = "dummy_assistant"
    FINAL_RESPONDER = "final_responder"
    ITEM_EXPERT = "item_expert"
    META_EXPERT = "meta_expert"
    SKILL_SELECTOR = "skill_selector"
    THEORIZER = "theorizer"
    UNIT_EXPERT = "unit_expert"
