"""Validate and capture assistant graphs for development and evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from domain.assistants.registry import AssistantRegistry
from domain.assistants.models import AssistantSpec
from devtools.assistants.definitions import load_development_spec

EDITABLE_FILES = ("system.md", "agent.json", "task.md")


@dataclass(frozen=True)
class AssistantDefinitions:
    """Pair runtime definitions with development-owned source and model state."""

    registry: AssistantRegistry
    source_files: dict[str, dict[str, str]] = field(default_factory=dict)
    resolved_models: dict[str, str] = field(default_factory=dict)

    def snapshot(self) -> AssistantDefinitions:
        """Return an isolated copy for conflict checks and runtime construction."""
        return AssistantDefinitions(
            registry=self.registry,
            source_files={
                name: dict(documents)
                for name, documents in self.source_files.items()
            },
            resolved_models=dict(self.resolved_models),
        )


def digest(value: Any) -> str:
    """Hash canonical JSON for source, graph, and revision identities."""
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def registry_from_files(files: dict[str, dict[str, str]]) -> AssistantDefinitions:
    """Parse and validate editable definitions in an isolated staging tree.

    Args:
        files: Complete editable file inventory keyed by assistant name.

    Returns:
        Validated runtime definitions paired with their source inventory.
    """
    specs = []
    with tempfile.TemporaryDirectory(prefix="assistant-specs-") as temporary:
        root = Path(temporary)
        for name, documents in files.items():
            if not name or Path(name).name != name or name in {".", ".."}:
                raise ValueError("Invalid assistant identity")
            if (
                set(documents) - set(EDITABLE_FILES)
                or not documents.get("system.md", "").strip()
            ):
                raise ValueError(
                    "A nonempty system.md and only editable files are required"
                )
            directory = root / name
            directory.mkdir()
            for filename, content in documents.items():
                (directory / filename).write_bytes(content.encode("utf-8"))
            if "agent.json" in documents:
                config = json.loads(documents["agent.json"])
                if not isinstance(config, dict):
                    raise ValueError("agent.json must contain a JSON object")
                allowed = {
                    "name",
                    "description",
                    "handoff_description",
                    "system_prompt",
                    "task_prompt",
                    "model",
                    "reasoning",
                    "tools",
                    "tool_groups",
                    "tool_names",
                    "include_all_tools",
                    "handoffs",
                    "handoff_names",
                    "resources",
                    "context",
                    "skills",
                    "playbooks",
                }
                unsupported = set(config) - allowed
                if unsupported:
                    raise ValueError(
                        "Unsupported agent.json keys: "
                        + ", ".join(sorted(unsupported))
                    )
                for key in (
                    "model",
                    "reasoning",
                    "name",
                    "description",
                    "handoff_description",
                    "system_prompt",
                    "task_prompt",
                ):
                    if config.get(key) is not None and not isinstance(config[key], str):
                        raise ValueError(key + " must be text")
                if isinstance(config.get("tools"), dict) and set(config["tools"]) - {
                    "groups",
                    "names",
                    "allow",
                    "include_all",
                    "all",
                }:
                    raise ValueError("Unsupported tools configuration")
            spec = load_development_spec(directory, root_dir=root)
            if spec.name != name:
                raise ValueError(
                    "Assistant identity changes require the lifecycle CLI"
                )
            specs.append(
                replace(
                    spec,
                    path=f"app/backend/src/domain/assistant_specs/{name}/system.md",
                )
            )
    registry = AssistantRegistry(specs)
    return AssistantDefinitions(
        registry=registry,
        source_files={name: dict(documents) for name, documents in files.items()},
    )


def capture(
    definitions: AssistantDefinitions | AssistantRegistry,
    names: list[str] | None = None,
) -> dict:
    """Freeze definitions and resolved model defaults independently of source."""
    registry = (
        definitions.registry
        if isinstance(definitions, AssistantDefinitions)
        else definitions
    )
    resolved_models = (
        definitions.resolved_models
        if isinstance(definitions, AssistantDefinitions)
        else {}
    )
    selected = names or list(registry.assistant_names)
    specs = {
        name: {
            **asdict(registry.get_spec(name)),
            "resolved_model": resolved_models.get(
                name, registry.get_spec(name).resolved_model()
            ),
        }
        for name in selected
    }
    value = json.loads(json.dumps({"version": 2, "specs": specs}))
    return {**value, "hash": digest(value)}


def registry_from_capture(graph: dict) -> AssistantDefinitions:
    """Restore a versioned graph and normalize historical capture fields."""
    if graph.get("version") not in (1, 2) or digest(
        {key: graph[key] for key in ("version", "specs")}
    ) != graph.get("hash"):
        raise ValueError("Invalid captured assistant graph")
    specs = []
    for name, definition in graph["specs"].items():
        config = {
            key: value for key, value in definition.items() if key != "resolved_model"
        }
        # Captures created before playbooks must not gain a new capability.
        config.setdefault("playbook_names", ())
        spec = AssistantSpec(**config)
        # Version 1 enforced chat's workflow restriction outside its spec. Keep
        # that historical behavior in the replay adapter; version 2 is spec-owned.
        if graph["version"] == 1 and spec.name == "chat":
            spec = replace(spec, skill_names=(), playbook_names=())
        if name != spec.name or not definition.get("resolved_model"):
            raise ValueError("Invalid captured assistant identity or model")
        specs.append(spec)
    registry = AssistantRegistry(specs)
    return AssistantDefinitions(
        registry=registry,
        resolved_models={
            name: definition["resolved_model"]
            for name, definition in graph["specs"].items()
        },
    )

