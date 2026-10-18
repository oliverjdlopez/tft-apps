"""ChatTFT agent configuration and prompt rendering."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from agents import Agent, RunContextWrapper

from domain.assistants.models import AssistantSpec
from domain.assistants.registry import AssistantRegistry, current_registry
from domain.resources.library import get_library, resource_entries
from domain.resources.models import ResourceLibrary
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
        if tuple(target.spec.name for target in targets) != spec.handoff_names:
            raise ValueError(f"Handoffs must match the specification for {spec.name!r}")
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
        clone = super().clone(**kwargs)
        clone.instructions = (
            clone.render_instructions
            if "instructions" not in kwargs and instructions == self.render_instructions
            else instructions
        )
        return clone

    @property
    def uses_resources(self) -> bool:
        """Whether this spec grants resources and declares the tool to read them."""
        spec = self.spec
        return bool(
            (spec.repository_context or spec.skill_names or spec.playbook_names)
            and (spec.include_all_tools or 'context' in spec.tool_group_keys
                 or 'read_resource' in spec.tool_names)
        )

    def load_resource_library(self) -> ResourceLibrary | None:
        """Load shared materials once if this assistant or a handoff uses them.

        Returns:
            The complete metadata snapshot for an invocation, or None when no
            node needs resources. Construction itself never loads materials.
        """
        pending = [self]
        seen = set()
        while pending:
            node = pending.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            if node.uses_resources:
                return get_library()
            pending.extend(node.handoffs)
        return None

    def resource_catalogue(
        self, library: ResourceLibrary | None,
    ) -> ResourceLibrary:
        """Select materials this assistant may expose and read under its own spec.

        Args:
            library: Shared invocation materials, without assistant permissions.

        Returns:
            A metadata view with this assistant's permitted IDs. The shared body
            cache supplies content but never grants access to additional IDs.
        """
        if library is None or not self.uses_resources:
            return ResourceLibrary()
        spec = self.spec
        entries = {}
        for resource_id, descriptor in library.entries.items():
            if resource_id.startswith(('skill:', 'playbook:')):
                namespace, package = resource_id.split('/', 1)[0].split(':', 1)
                configured = spec.skill_names if namespace == 'skill' else spec.playbook_names
                allowed = (
                    (spec.repository_context or bool(configured))
                    and (configured is None or package in configured)
                )
            else:
                allowed = spec.repository_context
            if allowed:
                entries[resource_id] = descriptor
        return ResourceLibrary(
            entries=entries,
            roots=tuple(resource_id for resource_id in library.roots if resource_id in entries),
            body_cache=library.body_cache,
        )

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
        started = time.perf_counter()
        parts = []
        if context.runtime.root_assistant == self.spec.name and context.runtime.system:
            parts.append(context.runtime.system)
        parts.append(self.spec.system_prompt)
        entries = resource_entries(self.resource_catalogue(context.resources))
        if entries:
            parts.append(
                "## Available resources\nUse `read_resource` with an exact ID to read a resource or browse an index."
            )
            for entry in entries:
                patches = ", ".join(str(patch) for patch in entry["patches"])
                scope = f"; patches: {patches}" if patches else ""
                parts.append(
                    f"- `{entry['id']}` — {entry['name']} ({entry['kind']}{scope}): {entry['description']}"
                )
        if context.timing is not None:
            context.timing["instruction_assembly_ms"] = round(
                context.timing.get("instruction_assembly_ms", 0.0)
                + (time.perf_counter() - started) * 1000,
                3,
            )
        return "\n\n".join(part.strip() for part in parts if part.strip())
