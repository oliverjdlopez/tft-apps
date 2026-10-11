"""Load assistant specifications from repository files."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any

from common.discoverers import discover_unique
from common.parsers import (
    first_markdown_heading,
    parse_frontmatter,
    parse_string_list,
)
from common.paths import find_repo_root
from domain.constants import OpenAIModels, ReasoningEfforts


logger = logging.getLogger(__name__)

ROOT_DIR = find_repo_root()
SPECS_DIR = ROOT_DIR / "app" / "backend" / "src" / "domain" / "assistant_specs"
ASSISTANT_SPECS_DIR = SPECS_DIR
AGENT_CONFIG_FILE = "agent.json"
TASK_PROMPT_FILE = "task.md"


def _read_agent_config(spec_dir: Path) -> dict[str, Any]:
    config_path = spec_dir / AGENT_CONFIG_FILE
    if not config_path.exists():
        return {}
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError(f"{config_path.relative_to(ROOT_DIR)} must contain a JSON object")
    return config


def _metadata_list(metadata: dict[str, str], *keys: str) -> tuple[str, ...]:
    for key in keys:
        if key in metadata:
            return parse_string_list(metadata[key], field=key)
    return ()


def _metadata_bool(metadata: dict[str, str], key: str) -> bool:
    value = metadata.get(key)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "all"}


def _read_tool_access(
    config: dict[str, Any],
    metadata: dict[str, str],
) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    raw_tools = config.get("tools")
    if isinstance(raw_tools, bool):
        return raw_tools, (), ()
    if isinstance(raw_tools, str | list | tuple):
        return False, (), parse_string_list(raw_tools, field="tools")
    if raw_tools is not None and not isinstance(raw_tools, dict):
        raise ValueError("tools must be a boolean, string, list, or object")

    tool_config = raw_tools or {}
    include_all = bool(
        tool_config.get("include_all")
        or tool_config.get("all")
        or config.get("include_all_tools")
        or _metadata_bool(metadata, "include_all_tools")
    )
    groups = parse_string_list(
        tool_config.get("groups", config.get("tool_groups")),
        field="tools.groups",
    ) or _metadata_list(metadata, "tool_groups", "tool_group_keys")
    names = parse_string_list(
        tool_config.get("names", tool_config.get("allow", config.get("tool_names"))),
        field="tools.names",
    ) or _metadata_list(metadata, "tool_names", "tools")
    return include_all, groups, names


def _read_handoffs(
    config: dict[str, Any],
    metadata: dict[str, str],
) -> tuple[str, ...]:
    raw_handoffs = config.get("handoffs", config.get("handoff_names"))
    if isinstance(raw_handoffs, dict):
        raw_handoffs = raw_handoffs.get("agents", raw_handoffs.get("names"))
    return parse_string_list(raw_handoffs, field="handoffs") or _metadata_list(
        metadata,
        "handoffs",
        "handoff_names",
    )


def _read_context_policy(config: dict[str, Any]) -> bool:
    """Read the repository-context policy for one assistant configuration.

    Args:
        config: Parsed assistant configuration object.

    Returns:
        Whether repository context may be selected for the assistant.

    Raises:
        ValueError: If the context policy has an unsupported key or value.
    """
    context = config.get("context") or {}
    if not isinstance(context, dict):
        raise ValueError("context must be an object")
    unsupported = sorted(set(context) - {"repository"})
    if unsupported:
        raise ValueError(f"unsupported context keys: {', '.join(unsupported)}")
    if "repository" in context and not isinstance(context["repository"], bool):
        raise ValueError("context.repository must be a boolean")
    return bool(context.get("repository"))


def _read_skill_access(config: dict[str, Any]) -> tuple[str, ...] | None:
    """Read the optional skill-name allowlist from an assistant configuration.

    Args:
        config: Parsed assistant configuration object.

    Returns:
        ``None`` when every skill is allowed, otherwise the configured names.

    Raises:
        ValueError: If ``skills`` is not a JSON array of unique strings.
    """
    if "skills" not in config:
        return None
    raw_skills = config["skills"]
    if not isinstance(raw_skills, list) or any(
        not isinstance(name, str) or not name.strip() for name in raw_skills
    ):
        raise ValueError("skills must be a list of non-empty strings")
    names = tuple(name.strip() for name in raw_skills)
    if len(names) != len(set(names)):
        raise ValueError("skills must not contain duplicate names")
    return names


def _spec_dir_for(path: Path) -> Path:
    return path if path.is_dir() else path.parent


def _system_path_for(path: Path) -> Path:
    return path / "system.md" if path.is_dir() else path

def _coerce_optional_enum(value: Any, enum_cls: type[Any], field: str) -> Any:
    if value is None or isinstance(value, enum_cls):
        return value
    try:
        return enum_cls(str(value).strip())
    except ValueError:
        valid = ", ".join(member.value for member in enum_cls)
        raise ValueError(f"{field} must be one of: {valid}") from None

@dataclass(frozen=True)
class AssistantSpec:
    """Immutable configuration used to construct one repository assistant."""

    name: str
    description: str
    handoff_description: str
    system_prompt: str
    task_prompt: str
    path: str
    # ``None`` means use the operator-configured OpenAI default. Individual
    # assistant specs can still pin a model explicitly in agent.json.
    model: OpenAIModels | None = None
    reasoning: ReasoningEfforts | None = ReasoningEfforts.MEDIUM
    include_all_tools: bool = False
    tool_group_keys: tuple[str, ...] = ()
    tool_names: tuple[str, ...] = ()
    handoff_names: tuple[str, ...] = ()
    repository_context: bool = False
    # ``None`` is intentionally permissive for backward-compatible specs;
    # an empty tuple explicitly prevents this assistant from reading skills.
    skill_names: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _coerce_optional_enum(self.model, OpenAIModels, "model"))
        object.__setattr__(
            self,
            "reasoning",
            _coerce_optional_enum(self.reasoning, ReasoningEfforts, "reasoning"),
        )

    def resolved_model(self) -> str:
        if self.model is not None:
            return self.model.value
        from core.config import load_config

        return load_config().models.openai_model

    def model_settings(self) -> Any:
        from agents import ModelSettings
        from openai.types.shared.reasoning import Reasoning

        reasoning = None
        if self.reasoning is not None:
            reasoning = Reasoning(effort=self.reasoning.value)
        return ModelSettings(reasoning=reasoning)


def load_assistant_spec(path: Path, *, root_dir: Path = ROOT_DIR) -> AssistantSpec:
    system_path = _system_path_for(path)
    spec_dir = _spec_dir_for(system_path)
    config = _read_agent_config(spec_dir)
    text = system_path.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    metadata = parsed.metadata
    task_prompt = parsed.body
    task_path = spec_dir / TASK_PROMPT_FILE
    body = task_prompt.strip()

    name = str(
        config.get("name")
        or metadata.get("name")
        or (system_path.parent.name if system_path.stem == "system" else system_path.stem)
    )
    configured_system_prompt = config.get("system_prompt") or metadata.get("system_prompt")
    system_prompt = str(configured_system_prompt).strip() if configured_system_prompt else body
    if task_path.exists():
        task_prompt = task_path.read_text(encoding="utf-8").strip()
    elif configured_system_prompt:
        task_prompt = body
    else:
        task_prompt = str(config.get("task_prompt") or metadata.get("task_prompt") or "").strip()

    description = str(
        config.get("description")
        or metadata.get("description")
        or first_markdown_heading(system_prompt)
        or name
    )
    handoff_description = str(
        config.get("handoff_description")
        or metadata.get("handoff_description")
        or description
    )
    include_all_tools, tool_group_keys, tool_names = _read_tool_access(config, metadata)
    repository_context = _read_context_policy(config)
    model = config.get("model") or metadata.get("model")
    reasoning = config.get("reasoning") or metadata.get("reasoning")
    spec_kwargs: dict[str, Any] = {
        "name": name,
        "description": description,
        "handoff_description": handoff_description,
        "system_prompt": system_prompt,
        "task_prompt": task_prompt.strip(),
        "path": str(system_path.relative_to(root_dir)),
        "include_all_tools": include_all_tools,
        "tool_group_keys": tool_group_keys,
        "tool_names": tool_names,
        "handoff_names": _read_handoffs(config, metadata),
        "repository_context": repository_context,
        "skill_names": _read_skill_access(config),
    }
    if model:
        spec_kwargs["model"] = str(model).strip()
    if reasoning:
        spec_kwargs["reasoning"] = str(reasoning).strip()
    return AssistantSpec(**spec_kwargs)


def discover_assistants_specs() -> list[AssistantSpec]:
    from common.assistant_workspace import recover

    recover(ROOT_DIR / '.runtime' / 'assistant-workspace', ASSISTANT_SPECS_DIR)
    return discover_unique(
        ASSISTANT_SPECS_DIR,
        ["*.md", "*/system.md"],
        load_assistant_spec,
        identity=lambda spec: spec.name.casefold(),
        skip_names={"readme.md", "agents.md"},
        on_error=lambda path, exc: logger.warning(
            "ignoring invalid assistant spec path=%s error=%s", path, exc
        ),
        on_duplicate=lambda path, spec: logger.warning(
            "ignoring duplicate assistant spec name=%s path=%s", spec.name, path
        ),
    )


__all__ = [
    "ASSISTANT_SPECS_DIR",
    "ROOT_DIR",
    "SPECS_DIR",
    "discover_assistants_specs",
    "load_assistant_spec",
]
