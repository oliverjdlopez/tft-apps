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



def test_prepared_handoffs_filter_shared_skills(tmp_path):
    """Root excludes skills; handoffs enforce their own allowlists on shared selections."""
    from dataclasses import replace
    root = _load_spec(tmp_path, {'handoffs': ['child', 'denied']})
    child = replace(root, name='child', handoff_names=(), skill_names=('allowed',))
    denied = replace(child, name='denied', skill_names=())
    registry = AssistantRegistry([root, child, denied])
    registry.configure_tools(get_tool=lambda name: None, get_tool_group=lambda name: None, list_tools=lambda: [])

    class Provider:
        """Select both workflows to exercise filtering at each rendering boundary."""
        async def aselect(self, query, **kwargs):
            """Return workflows without database or model calls."""
            return [SkillDefinition(name=name, description=name, body=name.upper(), path=name) for name in ('allowed', 'blocked')]

        def render(self, skills):
            """Make included workflows visible in rendered text."""
            return ' '.join(skill.body for skill in skills)

    invocation = asyncio.run(Assistant(root.name, registry=registry, skill_provider=Provider(), set_number=18).prepare('question'))
    wrapper = RunContextWrapper(invocation.context)
    assert invocation.agent.instructions(wrapper, invocation.agent) == 'BASE'
    rendered = {agent.name: agent.instructions(wrapper, agent) for agent in invocation.agent.handoffs}
    assert 'ALLOWED' in rendered['child'] and 'BLOCKED' not in rendered['child']
    assert rendered['denied'] == 'BASE'
