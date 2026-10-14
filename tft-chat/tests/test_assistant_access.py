"""Check current spec permissions and the prepared invocation boundary."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agents import RunContextWrapper
from domain.assistants import Assistant, AssistantRegistry
from domain.assistants.specs import AssistantSpec, load_assistant_spec
from domain.providers.models import SkillDefinition


def _load_spec(tmp_path: Path, config: dict) -> AssistantSpec:
    """Parse isolated source files without touching shipped definitions."""
    spec_dir = tmp_path / 'fixture'
    spec_dir.mkdir(parents=True)
    (spec_dir / 'system.md').write_text('BASE')
    (spec_dir / 'agent.json').write_text(json.dumps(config))
    return load_assistant_spec(spec_dir, root_dir=tmp_path)


def test_omitted_and_empty_access_are_distinct(tmp_path):
    """Omitted skills allow all while explicit empty lists deny access."""
    omitted = _load_spec(tmp_path / 'omitted', {})
    empty = _load_spec(tmp_path / 'empty', {'tools': {'groups': [], 'names': []}, 'skills': []})
    assert omitted.skill_names is None
    assert not omitted.include_all_tools
    assert empty.skill_names == () and empty.tool_names == ()


def test_named_access_is_preserved(tmp_path):
    """Canonical configuration retains explicitly declared capabilities."""
    spec = _load_spec(tmp_path, {'tools': {'names': ['resolve_tft_names']}, 'skills': ['allowed']})
    assert spec.tool_names == ('resolve_tft_names',)
    assert spec.skill_names == ('allowed',)


@pytest.mark.parametrize("value", [True, "all", {"all": True}, [1]])
def test_skills_requires_a_string_list(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValueError, match="skills must"):
        _load_spec(tmp_path, {"skills": value})





def test_selectors_are_absent_from_runtime_discovery():
    """Selection is owned by the running assistant through resource reads."""
    from domain.assistants import list_assistants
    assert not {'context_selector', 'skill_selector'} & set(list_assistants())
