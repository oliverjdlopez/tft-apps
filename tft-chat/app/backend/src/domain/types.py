"""Shared non-API, non-database type definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any






@dataclass(frozen=True)
class AssistantToolGroup:
    key: str
    label: str
    description: str
    tools: tuple[Any, ...]

    def get_tool(self, name: str) -> Any:
        """Return a tool in this group by its SDK tool name."""
        for tool in self.tools:
            if getattr(tool, "name", None) == name:
                return tool
        raise KeyError(f"Unknown tool in group {self.key!r}: {name}")

    def list_tools(self) -> tuple[Any, ...]:
        """Return all tools in this group in registration order."""
        return self.tools


@dataclass(frozen=True)
class AssistantTool:
    """A single explicitly declared, independently registered assistant tool.

    Applied by tool modules that expose one bounded tool and would otherwise
    have to wrap it in a single-member :class:`AssistantToolGroup` purely to
    register it. ``as_group`` lets the tool registry apply identical
    discovery and resolution logic to standalone tools and grouped tools.
    """

    key: str
    label: str
    description: str
    tool: Any

    def get_tool(self, name: str) -> Any:
        """Return this tool if ``name`` matches its SDK tool name."""
        if getattr(self.tool, "name", None) == name:
            return self.tool
        raise KeyError(f"Unknown tool {self.key!r}: {name}")

    def list_tools(self) -> tuple[Any, ...]:
        """Return this tool as a single-element tuple."""
        return (self.tool,)

    def as_group(self) -> AssistantToolGroup:
        """Return this tool represented as a single-tool :class:`AssistantToolGroup`.

        Registries fold standalone tools through this method so every
        downstream lookup (by name, by group key, or by metadata listing)
        stays on one code path regardless of how a tool module declared it.
        """
        return AssistantToolGroup(
            key=self.key,
            label=self.label,
            description=self.description,
            tools=(self.tool,),
        )


__all__ = [
    "AssistantTool",
    "AssistantToolGroup",
]
