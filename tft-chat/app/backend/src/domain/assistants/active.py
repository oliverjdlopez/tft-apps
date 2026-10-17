"""Lazy publication point for live assistant definitions."""

from __future__ import annotations

from threading import RLock

from domain.assistants.registry import AssistantRegistry
from domain.assistants.specs import discover_assistants_specs
from domain.assistants.utils import configure_tools


def load_runtime_registry() -> AssistantRegistry:
    """Load and validate the repository definitions used by live execution."""
    registry = AssistantRegistry(discover_assistants_specs())
    configure_tools(registry)
    registry.validate()
    return registry


class ActiveAssistantRegistry:
    """Publish complete registries while preserving existing snapshots."""

    def __init__(self) -> None:
        """Create an unloaded live registry publication point."""
        self._lock = RLock()
        self._registry: AssistantRegistry | None = None

    def current(self) -> AssistantRegistry:
        """Return the published registry, loading repository definitions lazily."""
        with self._lock:
            if self._registry is None:
                self._registry = load_runtime_registry()
            return self._registry

    def publish(self, registry: AssistantRegistry) -> None:
        """Publish a validated registry for subsequently created assistants."""
        candidate = registry.snapshot()
        candidate.validate()
        with self._lock:
            self._registry = candidate


active_assistant_registry = ActiveAssistantRegistry()


__all__ = [
    "ActiveAssistantRegistry",
    "active_assistant_registry",
    "load_runtime_registry",
]
