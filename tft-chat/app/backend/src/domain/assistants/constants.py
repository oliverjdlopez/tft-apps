from enum import StrEnum


class AssistantName(StrEnum):
    CHAT = "chat"
    COMP_EXPERT = "comp_expert"
    CONTEXT_SELECTOR = "context_selector"
    DATA_ANALYST = "data_analyst"
    DISTILL_TRANSCRIPT = "distill-transcript"
    DUMMY_ASSISTANT = "dummy_assistant"
    FINAL_RESPONDER = "final_responder"
    ITEM_EXPERT = "item_expert"
    META_EXPERT = "meta_expert"
    SKILL_SELECTOR = "skill_selector"
    THEORIZER = "theorizer"
    UNIT_EXPERT = "unit_expert"
