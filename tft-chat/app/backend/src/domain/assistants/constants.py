from enum import StrEnum


class AssistantName(StrEnum):
    ANALYZE_TRANSCRIPT = "analyze_transcript"
    CHAT = "chat"
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
