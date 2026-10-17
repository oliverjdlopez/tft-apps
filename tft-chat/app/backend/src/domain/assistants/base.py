"""Construct SDK assistant graphs and prepare them for execution."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import uuid4

from agents import Agent, RunConfig, RunContextWrapper, Runner, RunResult

from core.config import load_config
from domain.assistants.models import AssistantInvocation
from domain.assistants.registry import AssistantRegistry, current_registry
from domain.assistants.resources import prepare_resources, resource_entries
from domain.assistants.utils import invocation_input
from domain.runtime.activity import ActivityRunHooks, finalize_activity
from domain.runtime.models import AssistantRunContext, RuntimeSettings
from domain.tools.evidence.models import EvidenceStore


class BaseAssistant:
    """Own one SDK graph built for execution from frozen definitions.

    Create an instance for each independent execution. Use run/run_sync for
    ordinary execution or prepare when a consumer owns streaming and tracing.
    Read discovery metadata directly from the registry without constructing one.
    """

    def __init__(
        self,
        name: str,
        *,
        registry: AssistantRegistry | None = None,
        model: object | None = None,
        output_type: type[Any] | None = None,
        resolved_models: Mapping[str, str] | None = None,
        set_number: int | None = None,
        surface: str = "assistant",
    ) -> None:
        """Build the root SDK agent and handoffs with their fixed execution policy.

        Args:
            name: Registered root assistant name.
            registry: Optional isolated registry, including captured definitions.
            model: Optional request model propagated through all handoffs.
            output_type: Optional structured output contract for the root.
            resolved_models: Optional frozen model identifiers keyed by assistant.
            set_number: TFT set override; omission uses application configuration.
            surface: Execution surface recorded in the invocation context.
        """
        setup_started = time.perf_counter()
        if registry is None:
            registry = current_registry()
        self.name = name
        self.spec = registry.get_spec(name)
        self.surface = surface
        self.set_number = load_config().chat.set_number if set_number is None else set_number
        self._specs = {
            target: registry.get_spec(target)
            for target in registry.reachable_assistant_names[name]
        }
        frozen_models = dict(resolved_models or {})
        if model is None:
            for target, spec in self._specs.items():
                if target not in frozen_models:
                    frozen_models[target] = spec.resolved_model()
        handoffs = [
            ASSISTANT_CLASSES.get(target, BaseAssistant)(
                target, registry=registry, model=model, resolved_models=frozen_models,
                set_number=self.set_number, surface=surface,
            ).agent
            for target in registry.handoff_names[name]
        ]
        self.agent = Agent(
            name=name,
            handoff_description=self.spec.handoff_description,
            instructions=self.instructions,
            model=model if model is not None else frozen_models[name],
            model_settings=self.spec.model_settings(),
            tools=list(registry.tools[name]),
            handoffs=handoffs,
            output_type=output_type,
        )
        self._agent_setup_ms = round((time.perf_counter() - setup_started) * 1000, 3)

    def render_prompt(self, context: AssistantRunContext) -> str:
        """Compose this assistant's complete prompt from its spec and prepared state.

        Args:
            context: Shared run context containing prepared resources and caller policy.

        Returns:
            Instructions and permitted resource metadata, without resource bodies.
        """
        parts = []
        if context.runtime.root_assistant == self.name and context.runtime.system:
            parts.append(context.runtime.system)
        parts.append(self.spec.system_prompt)
        entries = resource_entries(context.resources, self.name)
        if entries:
            parts.append("## Available resources\nUse `read_resource` with an exact ID to read a resource or browse an index.")
            for entry in entries:
                patches = ", ".join(str(patch) for patch in entry['patches'])
                scope = f"; patches: {patches}" if patches else ""
                parts.append(f"- `{entry['id']}` — {entry['name']} ({entry['kind']}{scope}): {entry['description']}")
        return "\n\n".join(part.strip() for part in parts if part.strip())

    def instructions(self, wrapper: RunContextWrapper[Any], agent: Agent[Any]) -> str:
        """Adapt the SDK's two-argument callback to the prompt rendering override.

        Args:
            wrapper: SDK wrapper around the prepared application context.
            agent: SDK target; identity remains bound to this assistant for fallbacks.

        Returns:
            The prompt produced by this assistant's render_prompt implementation.
        """
        context = wrapper.context
        if not isinstance(context, AssistantRunContext):
            raise TypeError("assistant instructions require AssistantRunContext")
        started = time.perf_counter()
        prompt = self.render_prompt(context)
        if context.timing is not None:
            context.timing['instruction_assembly_ms'] = round(
                context.timing.get('instruction_assembly_ms', 0.0)
                + (time.perf_counter() - started) * 1000, 3,
            )
        return prompt

    async def prepare(
        self,
        input: str | Sequence[Mapping[str, str]],
        *,
        system: str | None = None,
        request_id: str | None = None,
        timing: dict[str, Any] | None = None,
    ) -> AssistantInvocation:
        """Prepare fresh run state without blocking the caller's event loop.

        Args:
            input: User text or conversation history.
            system: Optional caller prefix rendered only for the root.
            request_id: Optional caller identity; omission generates a fresh ID.
            timing: Optional request timing record shared with callbacks.

        Returns:
            The prepared invocation, with local catalogue loading done in a worker.
        """
        return await asyncio.to_thread(
            self.prepare_sync, input, system=system, request_id=request_id, timing=timing,
        )

    def prepare_sync(
        self,
        input: str | Sequence[Mapping[str, str]],
        *,
        system: str | None = None,
        request_id: str | None = None,
        timing: dict[str, Any] | None = None,
    ) -> AssistantInvocation:
        """Prepare input and fresh run state for this instance's SDK graph.

        Args:
            input: User text or conversation history with user/assistant roles.
            system: Optional caller prefix rendered only for the root.
            request_id: Optional caller identity; omission generates a fresh ID.
            timing: Optional request timing record shared with callbacks.

        Returns:
            The constructed agent, wrapped input, fresh typed context, and hooks.
        """
        run_input = invocation_input(input, self.spec.task_prompt)
        if timing is not None:
            timing["agent_setup_ms"] = self._agent_setup_ms
        resources = prepare_resources(
            specs=self._specs, set_number=self.set_number, timing=timing,
        )
        context = AssistantRunContext(
            runtime=RuntimeSettings(
                request_id=request_id or uuid4().hex, set_number=self.set_number,
                root_assistant=self.name, surface=self.surface, system=system,
            ),
            resources=resources, evidence=EvidenceStore(), timing=timing,
        )
        return AssistantInvocation(self.agent, run_input, context, ActivityRunHooks())

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
        """Prepare synchronously and execute through the SDK's synchronous runner.

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
            pass
        else:
            raise RuntimeError("BaseAssistant.run_sync cannot run inside an event loop; await run()")
        invocation = self.prepare_sync(input, system=system)
        cancelled = False
        try:
            return Runner.run_sync(
                invocation.agent, input=invocation.input,
                context=invocation.context, hooks=invocation.hooks,
                max_turns=max_turns, run_config=run_config,
            )
        except (asyncio.CancelledError, KeyboardInterrupt):
            cancelled = True
            raise
        finally:
            finalize_activity(invocation.context, cancelled=cancelled)


# The public constructor module installs the explicit class selection once.
# Keeping the shared mapping here lets handoffs select classes without importing
# the constructor or subclasses back into their base implementation.
ASSISTANT_CLASSES: dict[str, type[BaseAssistant]] = {}
