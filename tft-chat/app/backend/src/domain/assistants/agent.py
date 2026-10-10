"""SDK assistant with specification-owned instruction and provider behavior."""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from agents import Agent

from domain.assistants.runtime import prepare_resources
from domain.assistants.specs import AssistantSpec
from domain.assistants.utils import instruction_callback, render_instruction_layers
from domain.providers.context import DEFAULT_CONTEXT_PROVIDER
from domain.providers.models import ContextProvider, SkillProvider
from domain.providers.skills import DEFAULT_SKILL_PROVIDER
from domain.runtime.models import AssistantRunContext, PreparedResources


@dataclass(kw_only=True)
class AssistantAgent(Agent[AssistantRunContext]):
    """Own stable assistant policy while receiving mutable state per invocation.

    Provider defaults are shared dependencies, not invocation caches. Context
    overrides take precedence without mutating this agent or its handoff graph.
    """

    spec: AssistantSpec
    is_root: bool = True
    context_provider: ContextProvider = field(default_factory=lambda: DEFAULT_CONTEXT_PROVIDER)
    skill_provider: SkillProvider = field(default_factory=lambda: DEFAULT_SKILL_PROVIDER)

    def __post_init__(self) -> None:
        """Install dynamic rendering unless the caller supplied instructions."""
        if self.instructions is None:
            self.instructions = instruction_callback
        super().__post_init__()

    def resolve_context_provider(self, context: object) -> ContextProvider:
        """Resolve the invocation override or this agent's factual provider.

        Args:
            context: Local run context, including legacy untyped contexts.

        Returns:
            The effective provider for factual selection and rendering.
        """
        if isinstance(context, AssistantRunContext) and context.context_provider is not None:
            return context.context_provider
        return self.context_provider

    def resolve_skill_provider(self, context: object) -> SkillProvider:
        """Resolve the invocation override or this agent's workflow provider.

        Args:
            context: Local run context, including legacy untyped contexts.

        Returns:
            The effective provider for skill selection and rendering.
        """
        if isinstance(context, AssistantRunContext) and context.skill_provider is not None:
            return context.skill_provider
        return self.skill_provider

    async def prepare_resources(
        self,
        messages: Sequence[Mapping[str, str]],
        context: AssistantRunContext,
    ) -> PreparedResources:
        """Select and store shared resources before executing an invocation.

        Call once on the root agent per incoming request. Rendering and handoffs
        reuse the resulting snapshot without selecting again.

        Args:
            messages: Conversation used to derive the selector query.
            context: Invocation receiving the selections and timing metrics.

        Returns:
            The prepared resources also stored in the invocation context.
        """
        context.resources = await prepare_resources(
            messages,
            context_provider=self.resolve_context_provider(context),
            skill_provider=self.resolve_skill_provider(context),
            set_number=context.runtime.set_number,
            timing=context.timing,
        )
        return context.resources

    def render_instructions(self, context: object) -> str:
        """Render this agent's permitted layers without retrieving resources.

        Args:
            context: Invocation state or a legacy caller's untyped context.

        Returns:
            Durable instructions plus permitted prepared resource layers.
        """
        if not isinstance(context, AssistantRunContext):
            return self.spec.system_prompt
        started = time.perf_counter()
        base_instructions = self.spec.system_prompt
        if self.is_root and context.runtime.system:
            base_instructions = f"{context.runtime.system}\n\n{base_instructions}"
        instructions = render_instruction_layers(
            self.spec,
            context_provider=self.resolve_context_provider(context),
            skill_provider=self.resolve_skill_provider(context),
            skills=() if self.is_root else context.resources.skills,
            base_instructions=base_instructions,
            references=(
                context.resources.references if context.resources.query.strip() else ()
            ),
        )
        if context.timing is not None:
            # Rendering runs for every model step; selector timings remain tied
            # to the single preparation call before execution.
            context.timing["instruction_assembly_ms"] = round(
                context.timing.get("instruction_assembly_ms", 0.0)
                + (time.perf_counter() - started) * 1000,
                3,
            )
        return instructions
