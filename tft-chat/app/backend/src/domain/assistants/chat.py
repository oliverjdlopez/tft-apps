"""Chat-specific SDK instructions."""

import time

from agents import Agent, RunContextWrapper

from ..runtime.models import AssistantRunContext
from .assistant import Assistant
from domain.resources.library import resource_entries


class ChatAssistant(Assistant):
    """Own prompt composition for the user-facing chat assistant."""

    def render_instructions(self, wrapper: RunContextWrapper[AssistantRunContext], agent: Agent[AssistantRunContext]) -> str:
        """Present chat instructions and the permitted TFT reference catalogue.

        Args:
            wrapper: SDK wrapper containing this request's reference access.
            agent: SDK target; identity stays bound to this instance for fallbacks.

        Returns:
            Chat's complete prompt, including a concise reference directory.
        """
        context = wrapper.context
        if not isinstance(context, AssistantRunContext):
            raise TypeError("assistant instructions require AssistantRunContext")
        started = time.perf_counter()
        parts = []
        if context.runtime.root_assistant == self.spec.name and context.runtime.system:
            parts.append(context.runtime.system)
        parts.append(self.spec.system_prompt)
        entries = resource_entries(context.resources.catalogues.get(self.spec.name))
        if entries:
            parts.append("## Available TFT references\nUse `read_resource` with an exact ID to read a reference or browse an index.")
            for entry in entries:
                patches = ", ".join(str(patch) for patch in entry['patches'])
                scope = f"; patches: {patches}" if patches else ""
                parts.append(f"- `{entry['id']}` — {entry['name']} ({entry['kind']}{scope}): {entry['description']}")
        if context.timing is not None:
            context.timing['instruction_assembly_ms'] = round(
                context.timing.get('instruction_assembly_ms', 0.0)
                + (time.perf_counter() - started) * 1000, 3,
            )
        return "\n\n".join(part.strip() for part in parts if part.strip())
