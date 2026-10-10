"""Registry implementation for assistant definitions and graph metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
import threading

from domain.assistants.specs import AssistantSpec, discover_assistants_specs


def _tool_name(tool: Any) -> str:
    """Return the registered name for an SDK tool or Python callable.

    Args:
        tool: SDK tool or callable registered in a tool group.

    Returns:
        The tool's registered name.
    """
    return getattr(tool, "name", getattr(tool, "__name__", ""))


class AssistantRegistry:
    """Store assistant specs and resolve their graph and tool metadata."""

    def __init__(self, specs: list[AssistantSpec] | None = None) -> None:
        """Load all assistant specifications into the registry."""
        self._snapshot_lock = threading.RLock()
        self._specs: dict[str, AssistantSpec] = {}
        self._get_tool: Callable[[str], Any] | None = None
        self._get_tool_group: Callable[[str], Any] | None = None
        self._list_tools: Callable[[], list[Any]] | None = None
        if specs is None:
            self.reload()
        else:
            self._specs = {spec.name: spec for spec in specs}
        if specs is not None:
            self.source_files: dict[str, dict[str, str]] = {}

    def snapshot(self) -> AssistantRegistry:
        """Capture immutable specs and tool resolvers for one invocation."""
        with self._snapshot_lock:
            registry = AssistantRegistry(list(self._specs.values()))
            registry.source_files = {name: dict(files) for name, files in self.source_files.items()}
        registry._get_tool = self._get_tool
        registry._get_tool_group = self._get_tool_group
        registry._list_tools = self._list_tools
        return registry

    def install(self, registry: AssistantRegistry) -> None:
        """Install a complete validated snapshot without changing captured graphs."""
        with self._snapshot_lock:
            self._specs = dict(registry._specs)
            self.source_files = {name: dict(files) for name, files in registry.source_files.items()}

    def configure_tools(
        self,
        *,
        get_tool: Callable[[str], Any],
        get_tool_group: Callable[[str], Any],
        list_tools: Callable[[], list[Any]],
    ) -> None:
        """Configure direct access to the independent tool registry.

        Args:
            get_tool: Function returning one registered tool by name.
            get_tool_group: Function returning one registered group by key.
            list_tools: Function returning all registered tools.
        """
        self._get_tool = get_tool
        self._get_tool_group = get_tool_group
        self._list_tools = list_tools

    def get_spec(self, name: str) -> AssistantSpec:
        """Return a registered assistant specification.

        Args:
            name: Registered assistant name.

        Returns:
            The assistant specification.

        Raises:
            KeyError: If the assistant is not registered.
        """
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError(f"Unknown assistant: {name}") from None

    def get_handoff_names(self, name: str) -> list[str]:
        """Return validated direct handoff targets for an assistant.

        Args:
            name: Registered assistant name.

        Returns:
            Direct handoff assistant names in declaration order.

        Raises:
            KeyError: If the assistant or a handoff target is not registered.
        """
        spec = self.get_spec(name)
        names: list[str] = []
        for handoff_name in spec.handoff_names:
            if handoff_name == name:
                continue
            if handoff_name not in self._specs:
                raise KeyError(
                    f"Unknown handoff assistant {handoff_name!r} in {name!r}"
                ) from None
            names.append(handoff_name)
        return names

    def resolve_tools(self, spec: AssistantSpec) -> list[Any]:
        """Resolve an assistant specification to registered SDK tools.

        Args:
            spec: Assistant specification declaring tool names and groups.

        Returns:
            Deduplicated SDK tools in declared group and name order.

        Raises:
            KeyError: If a declared tool or tool group is not registered.
        """
        if (
            self._get_tool is None
            or self._get_tool_group is None
            or self._list_tools is None
        ):
            raise RuntimeError("assistant tool registry is not configured")
        if spec.include_all_tools:
            return self._list_tools()

        resolved: list[Any] = []
        seen: set[str] = set()
        for group_key in spec.tool_group_keys:
            for grouped_tool in self._get_tool_group(group_key).list_tools():
                name = _tool_name(grouped_tool)
                if name not in seen:
                    resolved.append(self._get_tool(name))
                    seen.add(name)
        for name in spec.tool_names:
            tool = self._get_tool(name)
            if name not in seen:
                resolved.append(tool)
                seen.add(name)
        return resolved

    def get_tools(self, name: str) -> list[Any]:
        """Return tools available directly to an assistant.

        Args:
            name: Registered assistant name.

        Returns:
            SDK tools resolved from the assistant specification.
        """
        return self.resolve_tools(self.get_spec(name))

    def list_tool_names(self, name: str) -> list[str]:
        """Return tool names available directly to an assistant.

        Args:
            name: Registered assistant name.

        Returns:
            Registered tool names in resolution order.
        """
        return [_tool_name(tool) for tool in self.get_tools(name)]

    def list_reachable_tool_names(self, name: str) -> list[str]:
        """Return tools callable by an assistant or any handoff target.

        Args:
            name: Root registered assistant name.

        Returns:
            Deduplicated tool names in handoff traversal order.
        """
        resolved: list[str] = []
        seen_tools: set[str] = set()
        seen_assistants: set[str] = set()

        def visit(assistant_name: str) -> None:
            """Collect tools while traversing the handoff graph.

            Args:
                assistant_name: Current registered assistant name.
            """
            if assistant_name in seen_assistants:
                return
            seen_assistants.add(assistant_name)
            for tool_name in self.list_tool_names(assistant_name):
                if tool_name not in seen_tools:
                    resolved.append(tool_name)
                    seen_tools.add(tool_name)
            for handoff_name in self.get_handoff_names(assistant_name):
                visit(handoff_name)

        visit(name)
        return resolved

    def list_assistants(self) -> list[str]:
        """Return registered assistant names sorted alphabetically."""
        return sorted(self._specs)

    def list_skill_names(self, name: str, available: list[str]) -> list[str]:
        """Return skill names an assistant may read in discovery order.

        Args:
            name: Registered assistant name.
            available: Discoverable repository skill names.

        Returns:
            All available names by default, or the configured allowlist subset.
        """
        configured = self.get_spec(name).skill_names
        if configured is None:
            return available
        allowed = set(configured)
        return [skill_name for skill_name in available if skill_name in allowed]

    def reload(self) -> None:
        """Reload assistant specifications from their source files."""
        specs = {spec.name: spec for spec in discover_assistants_specs()}
        from domain.assistants.specs import ROOT_DIR
        from pathlib import Path
        source_files = {spec.name: {
            filename: (ROOT_DIR / Path(spec.path).parent / filename).read_bytes().decode('utf-8')
            for filename in ('system.md', 'agent.json', 'task.md')
            if (ROOT_DIR / Path(spec.path).parent / filename).is_file()
        } for spec in specs.values()}
        with self._snapshot_lock:
            self._specs = specs
            self.source_files = source_files


assistant_registry = AssistantRegistry()


__all__ = ["AssistantRegistry"]
