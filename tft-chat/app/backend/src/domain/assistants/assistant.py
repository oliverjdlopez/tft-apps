"""Consumer entry points for snapshot-owned, dynamically prepared assistants."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from agents import Agent, RunConfig, Runner, RunResult

from core.config import load_config
from domain.assistants.models import AssistantInvocation
from domain.assistants.registry import AssistantRegistry, assistant_registry
from domain.assistants.runtime import prepare_resources
from domain.assistants.specs import AssistantSpec
from domain.assistants.token_logging import log_agent_graph
from domain.assistants.utils import instruction_callback, invocation_input, record_instructions
from domain.providers.context import RepositoryContextProvider
from domain.providers.models import ContextProvider, SkillProvider
from domain.providers.skills import RepositorySkillProvider
from domain.runtime.activity import ActivityRunHooks, finalize_activity
from domain.runtime.models import AssistantRunContext, RuntimeSettings
from domain.tools.evidence.models import EvidenceStore


class Assistant:
    """Own definitions and dependencies while creating fresh state for every run.

    Construct once to retain a definition snapshot, then use run/run_sync for
    ordinary execution or prepare when a consumer owns streaming and tracing.
    Instances never retain conversation history, evidence, or activity across runs.
    """

    def __init__(
        self,
        name: str,
        *,
        registry: AssistantRegistry | None = None,
        model: object | None = None,
        output_type: type[Any] | None = None,
        base_instructions_by_name: Mapping[str, str] | None = None,
        set_number: int | None = None,
        context_provider: ContextProvider | None = None,
        skill_provider: SkillProvider | None = None,
        surface: str = "assistant",
    ) -> None:
        """Capture the graph's policy, model defaults, and provider dependencies.

        Args:
            name: Registered root assistant name.
            registry: Optional isolated registry, including captured definitions.
            model: Optional request model propagated through all handoffs.
            output_type: Optional structured output contract for the root.
            base_instructions_by_name: Durable prompt replacements; callbacks,
                access rules, task wrappers, and model settings remain active.
            set_number: TFT set override; omission uses application configuration.
            context_provider: Optional factual provider for this instance.
            skill_provider: Optional workflow provider for this instance.
            surface: Execution surface recorded in the invocation context.
        """
        if registry is None:
            # Tool imports remain deferred until an execution consumer needs them.
            from domain.assistants import _configure_tools

            _configure_tools()
            registry = assistant_registry
        self._registry = registry.snapshot(
            base_instructions_by_name=base_instructions_by_name
        )
        self.name = name
        self.spec = self._registry.get_spec(name)
        self.model = model
        self.output_type = output_type
        self.surface = surface
        self.set_number = load_config().chat.set_number if set_number is None else set_number
        self._resolved_models = {
            key: self._registry.resolved_models[key]
            if key in self._registry.resolved_models
            else self._registry.get_spec(key).resolved_model()
            for key in self._registry.list_assistants()
        }
        self._registry.resolved_models = dict(self._resolved_models)
        # Selectors must use the same snapshot as handoffs, especially for drafts.
        self.context_provider = (
            context_provider if context_provider is not None
            else RepositoryContextProvider(registry=self._registry)
        )
        self.skill_provider = (
            skill_provider if skill_provider is not None
            else RepositorySkillProvider(registry=self._registry)
        )

    @classmethod
    def from_capture(cls, graph: dict[str, Any], name: str, **kwargs: Any) -> Assistant:
        """Restore a verified graph for draft trials or frozen experiments.

        Args:
            graph: Versioned captured definitions and their immutable hash.
            name: Root assistant in the capture.
            **kwargs: Instance settings accepted by the constructor.

        Returns:
            An assistant isolated from the application's active definitions.
        """
        from domain.assistants.capture import from_capture

        return cls(name, registry=from_capture(graph), **kwargs)

    @property
    def tool_names(self) -> list[str]:
        """Return direct tool names from this instance's definition snapshot."""
        return self._registry.list_tool_names(self.name)

    @property
    def reachable_tool_names(self) -> list[str]:
        """Return tools reachable through this instance's captured handoffs."""
        return self._registry.list_reachable_tool_names(self.name)

    def build_agent(self) -> Agent[Any]:
        """Construct a fresh SDK graph with dynamic instruction callbacks.

        Returns:
            A new root and handoffs using the instance's frozen model defaults.
        """
        agent = build_assistant(
            self._registry, self.name, model=self.model,
            output_type=self.output_type, resolved_models=self._resolved_models,
        )
        log_agent_graph(agent, task_prompt=self.spec.task_prompt)
        return agent

    async def prepare(
        self,
        input: str | Sequence[Mapping[str, str]],
        *,
        system: str | None = None,
        request_id: str | None = None,
        timing: dict[str, Any] | None = None,
        record: bool = False,
    ) -> AssistantInvocation:
        """Select resources once and create an independent SDK invocation.

        Args:
            input: User text or conversation history with user/assistant roles.
            system: Optional caller prefix rendered only for the root.
            request_id: Optional caller identity; omission generates a fresh ID.
            timing: Optional request timing record shared with callbacks.
            record: Whether to retain actual instructions and model settings.

        Returns:
            Agent, wrapped input, typed context, hooks, and optional provenance.
        """
        messages, run_input = invocation_input(input, self.spec.task_prompt)
        setup_started = time.perf_counter()
        agent = self.build_agent()
        if timing is not None:
            timing["agent_setup_ms"] = round(
                (time.perf_counter() - setup_started) * 1000, 3,
            )
        # Root skills are deliberately excluded. Do not invoke selectors for
        # resources that no reachable model step can consume (e.g. transcripts).
        specs: list[AssistantSpec] = []
        seen: set[str] = set()
        pending = [agent]
        while pending:
            current = pending.pop()
            if current.name in seen:
                continue
            seen.add(current.name)
            specs.append(self._registry.get_spec(current.name))
            pending.extend(current.handoffs)
        resources = await prepare_resources(
            messages, context_provider=self.context_provider,
            skill_provider=self.skill_provider, set_number=self.set_number,
            timing=timing,
            select_references=any(spec.repository_context for spec in specs),
            select_skills=any(
                spec.name != self.name and spec.skill_names != () for spec in specs
            ),
        )
        context = AssistantRunContext(
            runtime=RuntimeSettings(
                request_id=request_id or uuid4().hex, set_number=self.set_number,
                root_assistant=self.name, surface=self.surface, system=system,
            ),
            resources=resources, context_provider=self.context_provider,
            skill_provider=self.skill_provider, evidence=EvidenceStore(), timing=timing,
        )
        invocation = AssistantInvocation(agent, run_input, context, ActivityRunHooks())
        if record:
            record_instructions(invocation)
        return invocation

    async def run(
        self,
        input: str | Sequence[Mapping[str, str]],
        *,
        max_turns: int = 10,
        run_config: RunConfig | None = None,
        system: str | None = None,
    ) -> RunResult:
        """Prepare and execute one asynchronous invocation.

        Args:
            input: User text or supported conversation history.
            max_turns: SDK model-turn limit for this invocation.
            run_config: Optional SDK execution and tracing configuration.
            system: Optional caller prefix for root instructions.

        Returns:
            The SDK result, including final_output and its typed run context.
        """
        invocation = await self.prepare(input, system=system)
        try:
            return await Runner.run(
                invocation.agent, input=invocation.input,
                context=invocation.context, hooks=invocation.hooks,
                max_turns=max_turns, run_config=run_config,
            )
        finally:
            finalize_activity(invocation.context, cancelled=bool(
                asyncio.current_task() and asyncio.current_task().cancelling()
            ))

    def run_sync(
        self,
        input: str | Sequence[Mapping[str, str]],
        *,
        max_turns: int = 10,
        run_config: RunConfig | None = None,
        system: str | None = None,
    ) -> RunResult:
        """Prepare and execute from a synchronous consumer.

        Args:
            input: User text or supported conversation history.
            max_turns: SDK model-turn limit for this invocation.
            run_config: Optional SDK execution and tracing configuration.
            system: Optional caller prefix for root instructions.

        Returns:
            The same SDK result as run(). Use run() inside an active event loop.

        Raises:
            RuntimeError: If called inside an active event loop.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run(
                input, max_turns=max_turns, run_config=run_config, system=system,
            ))
        raise RuntimeError("Assistant.run_sync cannot run inside an event loop; await run()")


def build_assistant(
    registry: AssistantRegistry,
    name: str,
    *,
    model: object | None = None,
    output_type: type[Any] | None = None,
    resolved_models: Mapping[str, str] | None = None,
) -> Agent[Any]:
    """Construct a fresh graph with each agent's context policy installed.

    Args:
        registry: Assistant registry used for specs, handoffs, and tools.
        name: Root registered assistant name.
        model: Optional model override propagated through the graph.
        output_type: Optional structured output type for the root agent.
        resolved_models: Frozen model defaults keyed by assistant name.

    Returns:
        A fresh SDK agent and handoffs with default instruction renderers.

    Raises:
        ValueError: If the handoff graph contains a cycle.
    """
    def build(candidate: str, path: tuple[str, ...]) -> Agent[Any]:
        """Build one assistant and its handoff descendants.

        Args:
            candidate: Assistant currently being constructed.
            path: Ancestor names used for cycle detection.

        Returns:
            A fresh SDK agent for the candidate.

        Raises:
            ValueError: If the candidate already occurs in the path.
        """
        if candidate in path:
            cycle = " -> ".join((*path, candidate))
            raise ValueError(f"assistant handoff cycle: {cycle}")
        spec = registry.get_spec(candidate)
        handoffs = [
            build(handoff_name, (*path, candidate))
            for handoff_name in registry.get_handoff_names(candidate)
        ]
        resolved_model = model
        if resolved_model is None:
            resolved_model = (
                resolved_models[candidate]
                if resolved_models is not None and candidate in resolved_models
                else spec.resolved_model()
            )
        return Agent(
            name=spec.name,
            handoff_description=spec.handoff_description,
            instructions=instruction_callback(spec, root=not path),
            model=resolved_model,
            model_settings=spec.model_settings(),
            tools=registry.resolve_tools(spec),
            handoffs=handoffs,
            output_type=output_type if candidate == name else None,
        )

    return build(name, ())

