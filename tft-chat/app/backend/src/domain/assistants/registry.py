"""Validated assistant definitions and precomputed execution metadata."""

from __future__ import annotations

from types import MappingProxyType

from domain.assistants.models import AssistantSpec
from domain.assistants.specs import discover_assistants_specs
from domain.assistants.utils import resolve_tools


class AssistantRegistry:
    """Resolve and validate a complete assistant graph once at construction."""

    def __init__(self, specs: list[AssistantSpec]) -> None:
        """Build read-only lookup tables for execution and discovery.

        Args:
            specs: Complete definitions, including every declared handoff target.

        Raises:
            KeyError: If a tool, group, or handoff target is unknown.
            ValueError: If names are duplicated, models are invalid, or handoffs cycle.
        """
        from domain.tools import tool_name

        self.specs = MappingProxyType({spec.name: spec for spec in specs})
        if len(self.specs) != len(specs):
            raise ValueError("Duplicate assistant names")
        self.assistant_names = tuple(sorted(self.specs))
        self.tools = MappingProxyType({
            spec.name: tuple(resolve_tools(spec)) for spec in specs
        })
        self.tool_names = MappingProxyType({
            name: tuple(tool_name(tool) for tool in tools)
            for name, tools in self.tools.items()
        })
        self.handoff_names = MappingProxyType({
            spec.name: tuple(spec.handoff_names) for spec in specs
        })
        for spec in specs:
            spec.model_settings()
            if not spec.resolved_model().strip():
                raise ValueError("Model must be nonempty")
            for target in spec.handoff_names:
                if target not in self.specs:
                    raise KeyError(f"Unknown handoff assistant {target!r} in {spec.name!r}")

        reachable = {}

        def visit(name: str, path: tuple[str, ...]) -> tuple[str, ...]:
            """Validate handoff cycles and memoize each reachable graph."""
            if name in path:
                raise ValueError(f"assistant handoff cycle: {' -> '.join((*path, name))}")
            if name not in reachable:
                names = [name]
                for target in self.handoff_names[name]:
                    names.extend(visit(target, (*path, name)))
                reachable[name] = tuple(dict.fromkeys(names))
            return reachable[name]

        for name in self.assistant_names:
            visit(name, ())
        self.reachable_assistant_names = MappingProxyType(reachable)
        self.reachable_tool_names = MappingProxyType({
            name: tuple(dict.fromkeys(
                tool
                for target in targets
                for tool in self.tool_names[target]
            ))
            for name, targets in reachable.items()
        })

    def get_spec(self, name: str) -> AssistantSpec:
        """Return a definition or report an unknown assistant name."""
        try:
            return self.specs[name]
        except KeyError:
            raise KeyError(f"Unknown assistant: {name}") from None


# Runtime readers capture this reference once per operation. Specs publication
# belongs to devtools; isolated execution supplies its own registry explicitly.
registry: AssistantRegistry | None = None


def current_registry() -> AssistantRegistry:
    """Load repository definitions once for runtime use outside application startup.

    Loading is deferred so importing assistants never reads partially written
    Specs files before startup has recovered the development workspace journal.
    """
    global registry
    if registry is None:
        registry = AssistantRegistry(discover_assistants_specs())
    return registry
