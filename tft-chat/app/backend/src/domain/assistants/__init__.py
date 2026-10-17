"""Public ChatTFT agent configuration and registry API."""

from domain.assistants.chat import ChatAssistant
from domain.assistants.registry import AssistantRegistry
from domain.assistants.constants import ASSISTANT_SPECS_DIR, SPECS_DIR, AssistantName
from domain.assistants.utils import load_assistant_spec
from domain.assistants.assistant import Assistant, ASSISTANT_CLASSES
from domain.assistants.models import AssistantSpec


ASSISTANT_CLASSES[AssistantName.CHAT] = ChatAssistant

__all__ = [
    "ASSISTANT_SPECS_DIR",
    "SPECS_DIR",
    "AssistantRegistry",
    "Assistant",
    "ChatAssistant",
    "AssistantSpec",
    "load_assistant_spec",
]
