"""Load current application assistant specifications."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from common.discoverers import discover_files
from common.parsers import first_markdown_heading
from common.paths import find_repo_root
from domain.constants import OpenAIModels, ReasoningEfforts


ROOT_DIR = find_repo_root()
SPECS_DIR = ROOT_DIR / "app" / "backend" / "src" / "domain" / "assistant_specs"
ASSISTANT_SPECS_DIR = SPECS_DIR
AGENT_CONFIG_FILE = "agent.json"
TASK_PROMPT_FILE = "task.md"

_ALLOWED_CONFIG_KEYS = {
    "name",
    "description",
    "handoff_description",
    "model",
    "reasoning",
    "tools",
    "context",
    "handoffs",
    "skills",
    "playbooks",
}
def _coerce_optional_enum(value: Any, enum_cls: type[Any], field: str) -> Any:
    if value is None or isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except ValueError:
        valid = ", ".join(member.value for member in enum_cls)
        raise ValueError(f"{field} must be one of: {valid}") from None


def _string(value: Any, *, field: str) -> str:
    """Return one nonempty text field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be nonempty text")
    return value.strip()


def _string_list(value: Any, *, field: str) -> tuple[str, ...]:
    """Return a unique ordered tuple from a current-format JSON array."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field} must be a list of non-empty strings")
    names = tuple(item.strip() for item in value)
    if len(names) != len(set(names)):
        raise ValueError(f"{field} must not contain duplicate names")
    return names


def _read_agent_config(spec_dir: Path) -> dict[str, Any]:
    """Read and validate the current application configuration envelope."""
    config_path = spec_dir / AGENT_CONFIG_FILE
    if not config_path.exists():
        return {}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"{config_path} must contain a JSON object")
    unsupported = sorted(set(config) - _ALLOWED_CONFIG_KEYS)
    if unsupported:
        raise ValueError(f"unsupported agent.json keys: {', '.join(unsupported)}")
    return config


def _read_tool_access(
    config: dict[str, Any],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Read only the current tool list or structured tool object."""
    raw_tools = config.get("tools", [])
    if isinstance(raw_tools, list):
        return False, (), _string_list(raw_tools, field="tools")
    if not isinstance(raw_tools, dict):
        raise ValueError("tools must be a list or object")
    unsupported = sorted(set(raw_tools) - {"include_all", "groups", "names"})
    if unsupported:
        raise ValueError(f"unsupported tools keys: {', '.join(unsupported)}")
    include_all = raw_tools.get("include_all", False)
    if not isinstance(include_all, bool):
        raise ValueError("tools.include_all must be a boolean")
    groups = _string_list(raw_tools.get("groups", []), field="tools.groups")
    names = _string_list(raw_tools.get("names", []), field="tools.names")
    return include_all, groups, names


def _read_context_policy(config: dict[str, Any]) -> bool:
    """Read the explicit repository-context policy."""
    context = config.get("context", {"repository": False})
    if not isinstance(context, dict):
        raise ValueError("context must be an object")
    unsupported = sorted(set(context) - {"repository"})
    if unsupported:
        raise ValueError(f"unsupported context keys: {', '.join(unsupported)}")
    if set(context) != {"repository"} or not isinstance(context["repository"], bool):
        raise ValueError("context.repository must be a boolean")
    return context["repository"]


def _read_instruction_access(
    config: dict[str, Any], key: str,
) -> tuple[str, ...] | None:
    """Read an optional skill or playbook allowlist."""
    if key not in config:
        return None
    return _string_list(config[key], field=key)


@dataclass(frozen=True)
class AssistantSpec:
    """Immutable configuration used to construct one application assistant."""

    name: str
    description: str
    handoff_description: str
    system_prompt: str
    task_prompt: str
    path: str
    model: OpenAIModels | None = None
    reasoning: ReasoningEfforts | None = ReasoningEfforts.MEDIUM
    include_all_tools: bool = False
    tool_group_keys: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    handoff_names: tuple[str, ...] = ()
    repository_context: bool = False
    # Omission permits every package; an empty tuple explicitly denies access.
    skill_names: tuple[str, ...] | None = None
    playbook_names: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _coerce_optional_enum(self.model, OpenAIModels, "model"))
        object.__setattr__(
            self,
            "reasoning",
            _coerce_optional_enum(self.reasoning, ReasoningEfforts, "reasoning"),
        )

    def resolved_model(self) -> str:
        """Return the pinned model or the application's configured default."""
        if self.model is not None:
            return self.model.value
        from core.config import load_config

        return load_config().models.openai_model

    def model_settings(self) -> Any:
        """Build SDK model settings from the declared reasoning effort."""
        from agents import ModelSettings
        from openai.types.shared.reasoning import Reasoning

        reasoning = None
        if self.reasoning is not None:
            reasoning = Reasoning(effort=self.reasoning.value)
        return ModelSettings(reasoning=reasoning)


def load_assistant_spec(path: Path, *, root_dir: Path = ROOT_DIR) -> AssistantSpec:
    """Load one current directory-based application specification.

    Args:
        path: Assistant directory or its ``system.md`` path.
        root_dir: Root used to retain a repository-relative source path.

    Returns:
        A validated immutable runtime specification.

    Raises:
        ValueError: If the source uses an incomplete or historical format.
    """
    system_path = path / "system.md" if path.is_dir() else path
    if system_path.name != "system.md" or not system_path.is_file():
        raise ValueError("current assistant specifications require a system.md file")
    spec_dir = system_path.parent
    config = _read_agent_config(spec_dir)
    name = _string(config.get("name", spec_dir.name), field="name")
    if name != spec_dir.name:
        raise ValueError(
            f"assistant name {name!r} must match its directory {spec_dir.name!r}"
        )
    system_prompt = system_path.read_text(encoding="utf-8").strip()
    if not system_prompt:
        raise ValueError("system.md must contain nonempty instructions")
    if system_prompt.startswith("---\n"):
        raise ValueError("system.md frontmatter is supported only by development tooling")
    task_path = spec_dir / TASK_PROMPT_FILE
    task_prompt = task_path.read_text(encoding="utf-8").strip() if task_path.exists() else ""
    include_all_tools, tool_group_keys, tool_names = _read_tool_access(config)
    spec_kwargs: dict[str, Any] = {
        "name": name,
        "description": _string(
            config.get("description", first_markdown_heading(system_prompt) or name),
            field="description",
        ),
        "handoff_description": "",
        "system_prompt": system_prompt,
        "task_prompt": task_prompt,
        "path": str(system_path.relative_to(root_dir)),
        "include_all_tools": include_all_tools,
        "tool_group_keys": tool_group_keys,
        "tool_names": tool_names,
        "handoff_names": _string_list(config.get("handoffs", []), field="handoffs"),
        "repository_context": _read_context_policy(config),
        "skill_names": _read_instruction_access(config, "skills"),
        "playbook_names": _read_instruction_access(config, "playbooks"),
    }
    spec_kwargs["handoff_description"] = _string(
        config.get("handoff_description", spec_kwargs["description"]),
        field="handoff_description",
    )
    for key in ("model", "reasoning"):
        if key in config:
            value = config[key]
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{key} must be nonempty text or null")
            spec_kwargs[key] = value.strip() if isinstance(value, str) else None
    return AssistantSpec(**spec_kwargs)


def discover_assistants_specs() -> list[AssistantSpec]:
    """Load every current application specification or fail as one unit."""
    specs: list[AssistantSpec] = []
    seen: set[str] = set()
    for system_path in discover_files(ASSISTANT_SPECS_DIR, ["*/system.md"]):
        spec = load_assistant_spec(system_path)
        key = spec.name.casefold()
        if key in seen:
            raise ValueError(f"duplicate assistant name: {spec.name}")
        seen.add(key)
        specs.append(spec)
    return specs


__all__ = [
    "ASSISTANT_SPECS_DIR",
    "ROOT_DIR",
    "SPECS_DIR",
    "AssistantSpec",
    "discover_assistants_specs",
    "load_assistant_spec",
]
