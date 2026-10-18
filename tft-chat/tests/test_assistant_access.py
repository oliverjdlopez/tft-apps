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
from domain.assistants.utils import load_assistant_spec
from devtools.assistants.definitions import load_development_spec


def _current_config(**changes) -> dict:
    """Return a complete current-format fixture configuration."""
    return {
        "name": "fixture",
        "description": "Fixture",
        "handoff_description": "Fixture handoff",
        "tools": [],
        "resources": {"context": {"repository": False}},
        "handoffs": [],
        **changes,
    }


def _load_spec(tmp_path: Path, config: dict, *, loader=load_assistant_spec) -> AssistantSpec:
    """Parse isolated source files without touching shipped definitions."""
    spec_dir = tmp_path / 'fixture'
    spec_dir.mkdir(parents=True)
    (spec_dir / 'system.md').write_text('BASE')
    (spec_dir / 'agent.json').write_text(json.dumps(_current_config(**config)))
    return loader(spec_dir, root_dir=tmp_path)


@pytest.mark.parametrize('loader', [load_assistant_spec, load_development_spec])
@pytest.mark.parametrize('resources,expected', [
    ({}, (False, None, None)),
    ({'context': {'repository': True}, 'skills': [], 'playbooks': []}, (True, (), ())),
    ({'context': {'repository': False}, 'skills': ['general', 'general'],
      'playbooks': ['specific']}, (False, ('general',), ('specific',))),
])
def test_resource_settings_agree_across_loaders(tmp_path, loader, resources, expected):
    """Runtime and Specs interpret resource defaults and independent grants alike."""
    spec = _load_spec(tmp_path, {'resources': resources}, loader=loader)
    assert (spec.repository_context, spec.skill_names, spec.playbook_names) == expected


@pytest.mark.parametrize('loader', [load_assistant_spec, load_development_spec])
@pytest.mark.parametrize('resources,error', [
    (None, 'resources must be an object'),
    ([], 'resources must be an object'),
    ({'context': None}, 'resources.context must be an object'),
    ({'context': True}, 'resources.context must be an object'),
    ({'context': {'repository': 'false'}}, 'repository_context must be a boolean'),
    ({'context': {'unknown': True}}, 'unsupported resources.context keys'),
    ({'skill': []}, 'unsupported resources keys'),
    ({'skills': 'all'}, 'skill_names must'),
    ({'playbooks': [False]}, 'playbook_names must'),
])
def test_invalid_resource_settings_fail_in_both_loaders(tmp_path, loader, resources, error):
    """Malformed or misspelled permission fields cannot silently broaden access."""
    with pytest.raises(ValueError, match=error):
        _load_spec(tmp_path, {'resources': resources}, loader=loader)


@pytest.mark.parametrize('field,value', [('context', {'repository': True}), ('skills', []), ('playbooks', [])])
def test_live_loader_rejects_flat_resource_configuration(tmp_path, field, value):
    """Repository definitions have a single location for resource policy."""
    with pytest.raises(ValueError, match='nested under resources'):
        _load_spec(tmp_path, {field: value})


def test_development_loader_preserves_old_resource_configuration(tmp_path):
    """Historical draft resources remain readable but cannot mix schema shapes."""
    directory = tmp_path / 'legacy'
    directory.mkdir()
    (directory / 'system.md').write_text('Historical instructions')
    config = {'context': {'repository': True}, 'skills': [], 'playbooks': ['specific']}
    config_path = directory / 'agent.json'
    config_path.write_text(json.dumps(config))
    spec = load_development_spec(directory, root_dir=tmp_path)
    assert (spec.repository_context, spec.skill_names, spec.playbook_names) == (True, (), ('specific',))
    config_path.write_text(json.dumps({**config, 'resources': {'skills': ['general']}}))
    with pytest.raises(ValueError, match='nested under resources'):
        load_development_spec(directory, root_dir=tmp_path)


def test_omitted_and_empty_access_are_distinct(tmp_path):
    """Omitted skills allow all while explicit empty lists deny access."""
    omitted = _load_spec(tmp_path / 'omitted', {})
    empty = _load_spec(tmp_path / 'empty', {'tools': {'groups': [], 'names': []}, 'resources': {'skills': []}})
    assert omitted.skill_names is None
    assert not omitted.include_all_tools
    assert empty.skill_names == () and empty.tool_names == ()


def test_named_access_is_preserved(tmp_path):
    """Canonical configuration retains explicitly declared capabilities."""
    spec = _load_spec(tmp_path, {'tools': {'names': ['resolve_tft_names']}, 'resources': {'skills': ['allowed']}})
    assert spec.tool_names == ('resolve_tft_names',)
    assert spec.skill_names == ('allowed',)


@pytest.mark.parametrize("value", [True, "all", {"all": True}, [1]])
def test_skills_requires_a_string_list(tmp_path: Path, value: object) -> None:
    with pytest.raises(ValueError, match="skill_names must"):
        _load_spec(tmp_path, {"resources": {"skills": value}})





def test_selectors_are_absent_from_runtime_discovery():
    """Selection is owned by the running assistant through resource reads."""
    assert not {'context_selector', 'skill_selector'} & set(list(current_registry().assistant_names))


@pytest.mark.parametrize('value', [True, 'all', {'all': True}, [1], ['']])
def test_playbooks_require_nonempty_names(tmp_path, value):
    """Malformed guide allowlists fail before constructing an assistant graph."""
    with pytest.raises(ValueError, match='playbook_names must'):
        _load_spec(tmp_path, {'resources': {'playbooks': value}})


def test_playbook_access_is_independent_of_skills(tmp_path):
    """Omitted, empty, and named guide permissions survive spec parsing."""
    assert _load_spec(tmp_path / 'omitted', {}).playbook_names is None
    spec = _load_spec(tmp_path / 'named', {'resources': {'playbooks': ['specific-guide'], 'skills': []}})
    assert spec.playbook_names == ('specific-guide',) and spec.skill_names == ()
    spec = _load_spec(tmp_path / 'empty', {'resources': {'playbooks': [], 'skills': ['general-guidance']}})
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
    agent = Assistant.from_name("distill-transcript")
    with pytest.raises(TypeError, match="AssistantRunContext"):
        agent.instructions(RunContextWrapper(None), agent)



def test_workspace_configuration_accepts_and_captures_playbooks():
    """Draft validation and graph serialization retain independent guide access."""
    from devtools.assistants import capture, registry_from_capture, registry_from_files
    source = registry_from_files({'fixture': {
        'system.md': 'Use the specific guide when relevant.',
        'agent.json': json.dumps({'tools': {'groups': ['context']},
                                  'resources': {'context': {'repository': True},
                                                'skills': [], 'playbooks': ['specific-guide']}}),
    }})
    graph = capture(source)
    assert graph['specs']['fixture']['playbook_names'] == ['specific-guide']
    restored = registry_from_capture(graph).registry.get_spec('fixture')
    assert restored.repository_context is True
    assert restored.playbook_names == ('specific-guide',) and restored.skill_names == ()
