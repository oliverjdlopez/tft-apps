"""Select the concrete runtime assistant class for a registered name."""

from typing import Any

from domain.assistants.base import ASSISTANT_CLASSES, BaseAssistant
from domain.assistants.chat import ChatAssistant
from domain.assistants.constants import AssistantName


ASSISTANT_CLASSES[AssistantName.CHAT] = ChatAssistant


class Assistant:
    """Select a concrete assistant by name and return that initialized object.

    Import BaseAssistant or a concrete subclass directly when class selection is
    unnecessary. This constructor adds no proxy around the returned assistant.
    """

    def __new__(cls, name: str, **kwargs: Any) -> BaseAssistant:
        """Initialize the selected class with the requested definition and options.

        Args:
            name: Registered definition to execute.
            **kwargs: Constructor options for the concrete assistant.

        Returns:
            A fully initialized BaseAssistant or specialized subclass instance.
        """
        return ASSISTANT_CLASSES.get(name, BaseAssistant)(name, **kwargs)
