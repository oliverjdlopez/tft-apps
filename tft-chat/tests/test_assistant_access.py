from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.assistants import registry
from domain.assistants.registry import (
    assistant_reachable_names,
    assistant_skill_names,
    list_assistants,
)
from domain.assistants.runtime import build_assistant_instructions
from domain.assistants.specs import load_assistant_spec
from domain.providers.skills import (
    SkillDefinition,
    list_skill_names,
)
from domain.tools import list_tool_names, resolve_tool_names
from domain.types import AssistantSpec
from services.chat_service import ChatMessage, ChatRequest, build_chat_instructions


def _load_spec(tmp_path: Path, config: dict) -> AssistantSpec:
    spec_dir = tmp_path / "fixture"
    spec_dir.mkdir(parents=True)
    (spec_dir / "system.md").write_text("# Fixture\n", encoding="utf-8")
    (spec_dir / "agent.json").write_text(json.dumps(config), encoding="utf-8")
    return load_assistant_spec(spec_dir, root_dir=tmp_path)


def test_access_lists_default_to_none_and_accept_all(tmp_path: Path) -> None:
    omitted = _load_spec(tmp_path / "omitted", {})
    empty = _load_spec(tmp_path / "empty", {"tools": [], "skills": []})
    all_access = _load_spec(
        tmp_path / "all",
        {"tools": ["all"], "skills": ["all"]},
    )

    assert omitted.include_all_tools is False
    assert omitted.include_all_skills is False
    assert empty.include_all_tools is False
    assert empty.tool_names == ()
    assert empty.include_all_skills is False
    assert empty.skill_names == ()
    assert all_access.include_all_tools is True
    assert all_access.include_all_skills is True
    assert resolve_tool_names(include_all=all_access.include_all_tools) == list_tool_names()


def test_named_access_lists_are_preserved(tmp_path: Path) -> None:
    spec = _load_spec(
        tmp_path,
        {
            "tools": ["resolve_tft_names"],
            "skills": ["tft-statistical-reasoning"],
        },
    )

    assert spec.tool_names == ("resolve_tft_names",)
    assert spec.skill_names == ("tft-statistical-reasoning",)


def test_omitted_tools_does_not_fall_back_to_markdown_metadata(tmp_path: Path) -> None:
    spec_dir = tmp_path / "fixture"
    spec_dir.mkdir()
    (spec_dir / "system.md").write_text(
        "---\ntools: [resolve_tft_names]\ninclude_all_tools: true\n---\n# Fixture\n",
        encoding="utf-8",
    )
    (spec_dir / "agent.json").write_text("{}\n", encoding="utf-8")

    spec = load_assistant_spec(spec_dir, root_dir=tmp_path)

    assert spec.include_all_tools is False
    assert spec.tool_group_keys == ()
    assert spec.tool_names == ()


@pytest.mark.parametrize("field", ["tools", "skills"])
def test_all_access_sentinel_must_be_used_alone(
    tmp_path: Path, field: str
) -> None:
    with pytest.raises(ValueError, match="must be used alone"):
        _load_spec(tmp_path, {field: ["all", "named-entry"]})


@pytest.mark.parametrize("value", [True, "all", {"all": True}, [1]])
def test_skills_requires_a_string_list(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValueError, match="skills must"):
        _load_spec(tmp_path, {"skills": value})


def test_every_shipped_assistant_enables_every_discoverable_skill() -> None:
    discovered = list_skill_names()

    assert "tft-artifact-items" in discovered
    assert len(discovered) == 7
    assert all(assistant_skill_names(name) == discovered for name in list_assistants())


def test_named_skill_access_limits_runtime_candidates(monkeypatch) -> None:
    allowed = SkillDefinition(
        name="allowed-skill",
        description="Allowed.",
        body="ALLOWED SKILL BODY",
        path="allowed-skill/SKILL.md",
    )
    denied = SkillDefinition(
        name="denied-skill",
        description="Denied.",
        body="DENIED SKILL BODY",
        path="denied-skill/SKILL.md",
    )

    class FakeSkillProvider:
        def discover(self):
            return [allowed, denied]

        def select(self, query, *, allowed_names=None):
            assert query == "Analyze this"
            assert allowed_names == ("allowed-skill",)
            return [allowed]

        def render(self, skills):
            return "\n".join(skill.body for skill in skills)

    monkeypatch.setitem(
        registry._PROMPT_SPECS,
        "limited",
        AssistantSpec(
            name="limited",
            description="Limited",
            handoff_description="Limited",
            system_prompt="BASE",
            task_prompt="",
            path="limited/system.md",
            skill_names=("allowed-skill",),
        ),
    )

    rendered = build_assistant_instructions(
        "limited",
        "Analyze this",
        skill_provider=FakeSkillProvider(),
    )

    assert "ALLOWED SKILL BODY" in rendered
    assert "DENIED SKILL BODY" not in rendered


def test_chat_root_suppresses_skills_and_all_reachable_handoffs_receive_them() -> None:
    skill = SkillDefinition(
        name="selected-skill",
        description="Selected.",
        body="SELECTED SKILL BODY",
        path="selected-skill/SKILL.md",
    )

    class FakeSkillProvider:
        def select(self, query, *, allowed_names=None):
            assert allowed_names is None
            return [skill]

        def render(self, skills):
            return "\n".join(item.body for item in skills)

    class FakeContextProvider:
        def select(self, query, *, set_number=None):
            return []

        def render(self, references):
            return ""

    root, handoffs, _tools, _references, selected = build_chat_instructions(
        ChatRequest(
            model="gpt-6-luna",
            messages=[ChatMessage(role="user", content="Analyze artifact items")],
        ),
        context_provider=FakeContextProvider(),
        skill_provider=FakeSkillProvider(),
    )

    assert "SELECTED SKILL BODY" not in root
    assert list(handoffs) == assistant_reachable_names("chat")
    assert all("SELECTED SKILL BODY" in instructions for instructions in handoffs.values())
    assert selected == (skill,)
