from ..runtime.models import AssistantRunContext
from .base import BaseAssistant
from .resources import resource_entries


class ChatAssistant(BaseAssistant):
    """Own prompt composition for the user-facing chat assistant."""

    def render_prompt(self, context: AssistantRunContext) -> str:
        """Present chat instructions and the permitted TFT reference catalogue.

        Args:
            context: Shared run context with prepared reference access.

        Returns:
            Chat's complete prompt, including a concise reference directory.
        """
        parts = []
        if context.runtime.root_assistant == self.name and context.runtime.system:
            parts.append(context.runtime.system)
        parts.append(self.spec.system_prompt)
        entries = resource_entries(context.resources, self.name)
        if entries:
            parts.append("## Available TFT references\nUse `read_resource` with an exact ID to read a reference or browse an index.")
            for entry in entries:
                patches = ", ".join(str(patch) for patch in entry['patches'])
                scope = f"; patches: {patches}" if patches else ""
                parts.append(f"- `{entry['id']}` — {entry['name']} ({entry['kind']}{scope}): {entry['description']}")
        return "\n\n".join(part.strip() for part in parts if part.strip())