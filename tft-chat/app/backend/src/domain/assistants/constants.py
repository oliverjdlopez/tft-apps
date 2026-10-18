from enum import StrEnum

from common.paths import find_repo_root


ROOT_DIR = find_repo_root()
SPECS_DIR = ROOT_DIR / "app" / "backend" / "src" / "domain" / "assistants" / "specs"
ASSISTANT_SPECS_DIR = SPECS_DIR


class AssistantName(StrEnum):
    CHAT = "chat"
    COMP_EXPERT = "comp_expert"
    DATA_ANALYST = "data_analyst"
    DISTILL_TRANSCRIPT = "distill-transcript"
    DUMMY_ASSISTANT = "dummy_assistant"
    FINAL_RESPONDER = "final_responder"
    ITEM_EXPERT = "item_expert"
    META_EXPERT = "meta_expert"
    THEORIZER = "theorizer"
    UNIT_EXPERT = "unit_expert"
