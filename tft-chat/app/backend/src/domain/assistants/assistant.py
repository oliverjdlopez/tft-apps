"""ChatTFT agent configuration and prompt rendering."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, RunContextWrapper

from domain.assistants.models import AssistantSpec
from domain.assistants.registry import AssistantRegistry, current_registry
from domain.resources.library import resource_entries
from domain.assistants.utils import resolve_tools
from domain.runtime.models import AssistantRunContext

ASSISTANT_CLASSES: dict[str, type[Assistant]] = {}


@dataclass
class Assistant(Agent[AssistantRunContext]):
    """An SDK agent configured by a ChatTFT spec, with no execution state.

    Use from_name to construct a registered graph or from_spec for an explicit
    node. Runtime supplies context when the SDK calls render_instructions.
    """

    spec: AssistantSpec = field(kw_only=True)

    def __post_init__(self) -> None:
        """Bind the default renderer and retain the SDK's field validation."""
        if self.instructions is None:
            self.instructions = self.render_instructions
        super().__post_init__()

    @classmethod
    def from_spec(
        cls,
        spec: AssistantSpec,
        *,
        model: Any = None,
        tools: list[Any] | None = None,
        handoffs: list[Assistant] | None = None,
        output_type: Any = None,
    ) -> Assistant:
        """Configure one node from a spec and explicitly constructed handoffs.

        Args:
            spec: Immutable prompt, model, tool, and access configuration.
            model: Optional SDK model or identifier overriding the spec default.
            tools: Pre-resolved tools; omission resolves the spec declarations.
            handoffs: Constructed targets matching the spec's handoff names.
            output_type: Optional SDK structured-output contract.

        Returns:
            An SDK-compatible assistant without invocation state.
        """
        targets = list(handoffs or ())

        # Check that constructed targets match the declared handoffs.
        if tuple(target.spec.name for target in targets) != spec.handoff_names:
            raise ValueError(f"Handoffs must match the specification for {spec.name!r}")

        # Construct the node after validating its outgoing edges.
        return cls(
            name=spec.name,
            spec=spec,
            handoff_description=spec.handoff_description,
            model=model if model is not None else spec.resolved_model(),
            model_settings=spec.model_settings(),
            tools=list(resolve_tools(spec) if tools is None else tools),
            handoffs=targets,
            output_type=output_type,
        )

    @classmethod
    def from_name(
        cls,
        name: str,
        *,
        registry: AssistantRegistry | None = None,
        model: Any = None,
        output_type: Any = None,
    ) -> Assistant:
        """Construct a fresh graph from one validated registry snapshot.

        Args:
            name: Registered root identity.
            registry: Optional isolated definitions; otherwise use current specs.
            model: Request model override propagated to every handoff.
            output_type: Structured-output contract for the root only.

        Returns:
            A configured root with specialized classes selected for every node.
        """
        source = registry if registry is not None else current_registry()
        source.get_spec(name)

        # Resolve the effective model for every reachable assistant.
        models = {
            target: (
                model if model is not None else source.get_spec(target).resolved_model()
            )
            for target in source.reachable_assistant_names[name]
        }

        def build(target: str) -> Assistant:
            """Use the same explicit class selection for roots and handoffs."""
            implementation = (
                cls
                if target == name and cls is not Assistant
                else ASSISTANT_CLASSES.get(target, Assistant)
            )

            # Build this node with its selected class and resolved children.
            return implementation.from_spec(
                source.get_spec(target),
                model=models[target],
                tools=list(source.tools[target]),
                handoffs=[build(child) for child in source.handoff_names[target]],
                output_type=output_type if target == name else None,
            )

        return build(name)

    def clone(self, **kwargs: Any) -> Assistant:
        """Preserve SDK cloning while binding the default renderer to the copy.

        Explicit instruction overrides, including development recording wrappers,
        retain the SDK's normal shallow-copy behavior.
        """
        instructions = kwargs.get("instructions", self.instructions)

        # Preserve SDK clone behavior before rebinding the default renderer.
        clone = super().clone(**kwargs)

        # Keep the default renderer bound to the cloned assistant instance.
        clone.instructions = (
            clone.render_instructions
            if "instructions" not in kwargs and instructions == self.render_instructions
            else instructions
        )
        return clone

    def render_instructions(
        self,
        wrapper: RunContextWrapper[AssistantRunContext],
        agent: Agent[AssistantRunContext],
    ) -> str:
        """Render this assistant's instructions directly for the SDK.

        Args:
            wrapper: SDK wrapper containing this request's application state.
            agent: SDK target; identity stays bound to this instance for fallbacks.

        Returns:
            Instructions and permitted resource metadata, without resource bodies.
        """
        context = wrapper.context
        if not isinstance(context, AssistantRunContext):
            raise TypeError("assistant instructions require AssistantRunContext")

        # Validate context before collecting prompt sections and timing.
        started = time.perf_counter()
        parts = self._base_instruction_parts(context)
        resource_instructions = self._resource_instructions(context)

        # Include resource guidance only when permitted entries exist.
        if resource_instructions:
            parts.append(resource_instructions)

        # Record rendering cost when the invocation exposes timing state.
        if context.timing is not None:
            context.timing["instruction_assembly_ms"] = round(
                context.timing.get("instruction_assembly_ms", 0.0)
                + (time.perf_counter() - started) * 1000,
                3,
            )

        # Return the complete prompt without empty sections.
        return "\n\n".join(part.strip() for part in parts if part.strip())

    def _base_instruction_parts(self, context: AssistantRunContext) -> list[str]:
        """Return the root prefix and this assistant's system prompt, in order.

        Args:
            context: Invocation state supplying the optional root system prefix.

        Returns:
            Prompt sections preceding the available-resource catalogue.
        """
        if context.runtime.root_assistant == self.spec.name and context.runtime.system:
            return [context.runtime.system, self.spec.system_prompt]
        return [self.spec.system_prompt]

    def _resource_instructions(self, context: AssistantRunContext) -> str:
        """Render metadata for resources this assistant is allowed to read.

        Args:
            context: Invocation state containing the shared resource library.

        Returns:
            Available-resource guidance and entries, or an empty string.
        """
        entries = [
            entry
            for entry in resource_entries(context.resources)
            if self.spec.allows_resource(entry["id"])
        ]
        if not entries:
            return ""

        parts = [
            "## Available resources\nUse `read_resource` with an exact ID to read a resource or browse an index."
        ]

        # Format each permitted resource as one catalogue entry.
        for entry in entries:
            patches = ", ".join(str(patch) for patch in entry["patches"])
            scope = f"; patches: {patches}" if patches else ""
            parts.append(
                f"- `{entry['id']}` — {entry['name']} ({entry['kind']}{scope}): {entry['description']}"
            )

        # Join the catalogue guidance and its formatted entries.
        return "\n\n".join(part.strip() for part in parts if part.strip())
