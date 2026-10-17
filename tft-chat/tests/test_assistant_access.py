"""Check current spec permissions and the prepared invocation boundary."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agents import RunContextWrapper
from domain.assistants import Assistant, AssistantRegistry
from domain.assistants.registry import current_registry
from domain.assistants.models import AssistantSpec
from domain.assistants.specs import load_assistant_spec
from devtools.assistants.definitions import load_development_spec


def _current_config(**changes) -> dict:
    """Return a complete current-format fixture configuration."""
    return {
        "name": "fixture",
        "description": "Fixture",
        "handoff_description": "Fixture handoff",
        "tools": [],
        "context": {"repository": False},
        "handoffs": [],
        **changes,
    }


def _load_spec(tmp_path: Path, config: dict) -> AssistantSpec:
    """Parse isolated source files without touching shipped definitions."""
    spec_dir = tmp_path / 'fixture'
    spec_dir.mkdir(parents=True)
    (spec_dir / 'system.md').write_text('BASE')
    (spec_dir / 'agent.json').write_text(json.dumps(_current_config(**config)))
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
    with pytest.raises(ValueError, match="skill_names must"):
        _load_spec(tmp_path, {"skills": value})





def test_selectors_are_absent_from_runtime_discovery():
    """Selection is owned by the running assistant through resource reads."""
    assert not {'context_selector', 'skill_selector'} & set(list(current_registry().assistant_names))


@pytest.mark.parametrize('value', [True, 'all', {'all': True}, [1], ['']])
def test_playbooks_require_nonempty_names(tmp_path, value):
    """Malformed guide allowlists fail before constructing an assistant graph."""
    with pytest.raises(ValueError, match='playbook_names must'):
        _load_spec(tmp_path, {'playbooks': value})


def test_playbook_access_is_independent_of_skills(tmp_path):
    """Omitted, empty, and named guide permissions survive spec parsing."""
    assert _load_spec(tmp_path / 'omitted', {}).playbook_names is None
    spec = _load_spec(tmp_path / 'named', {'playbooks': ['specific-guide'], 'skills': []})
    assert spec.playbook_names == ('specific-guide',) and spec.skill_names == ()
    spec = _load_spec(tmp_path / 'empty', {'playbooks': [], 'skills': ['general-guidance']})
    assert spec.playbook_names == () and spec.skill_names == ('general-guidance',)


def test_live_loader_rejects_historical_aliases_and_standalone_specs(tmp_path):
    """Keep compatibility syntax out of application definition loading."""
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _load_spec(tmp_path / "alias", {"tool_groups": ["context"]})
    standalone = tmp_path / "legacy.md"
    standalone.write_text("# Legacy\n", encoding="utf-8")
    with pytest.raises(ValueError, match="system.md"):
        load_assistant_spec(standalone, root_dir=tmp_path)


def test_development_loader_retains_historical_definition_support(tmp_path):
    """Older authored artifacts remain readable only through devtools."""
    legacy = tmp_path / "legacy.md"
    legacy.write_text(
        "---\nname: legacy\ntool_groups: context\n---\n# Legacy instructions\n",
        encoding="utf-8",
    )
    spec = load_development_spec(legacy, root_dir=tmp_path)
    assert spec.name == "legacy"
    assert spec.tool_group_keys == ("context",)
    assert spec.system_prompt == "# Legacy instructions"


def test_instruction_callbacks_require_prepared_application_context():
    """Raw SDK execution cannot silently omit request policy and resources."""
    agent = Assistant("distill-transcript").agent
    with pytest.raises(TypeError, match="AssistantRunContext"):
        agent.instructions(RunContextWrapper(None), agent)



def test_workspace_configuration_accepts_and_captures_playbooks():
    """Draft validation and graph serialization retain independent guide access."""
    from devtools.assistants import capture, registry_from_capture, registry_from_files
    source = registry_from_files({'fixture': {
        'system.md': 'Use the specific guide when relevant.',
        'agent.json': json.dumps({'tools': {'groups': ['context']},
                                  'skills': [], 'playbooks': ['specific-guide']}),
    }})
    graph = capture(source)
    assert graph['specs']['fixture']['playbook_names'] == ['specific-guide']
    restored = registry_from_capture(graph).registry.get_spec('fixture')
    assert restored.playbook_names == ('specific-guide',) and restored.skill_names == ()
