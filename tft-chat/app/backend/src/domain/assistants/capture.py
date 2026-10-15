"""Validate and capture complete assistant graphs without global substitution."""
from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from domain.assistants.registry import AssistantRegistry
from domain.assistants.specs import AssistantSpec, load_assistant_spec
from domain.assistants.utils import configure_tools

EDITABLE_FILES = ('system.md', 'agent.json', 'task.md')


def digest(value: Any) -> str:
    """Hash canonical JSON for source, graph, and revision identities."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def registry_from_files(files: dict[str, dict[str, str]]) -> AssistantRegistry:
    """Parse and validate every assistant together in an isolated staging tree.

    Args:
        files: Complete editable file inventory keyed by existing assistant name.

    Returns:
        A validated registry whose specifications never refer to staging paths.
    """
    specs = []
    with tempfile.TemporaryDirectory(prefix='assistant-specs-') as temporary:
        root = Path(temporary)
        for name, documents in files.items():
            if not name or Path(name).name != name or name in {'.', '..'}:
                raise ValueError('Invalid assistant identity')
            if set(documents) - set(EDITABLE_FILES) or not documents.get('system.md', '').strip():
                raise ValueError('A nonempty system.md and only editable files are required')
            directory = root / name
            directory.mkdir()
            for filename, content in documents.items():
                (directory / filename).write_bytes(content.encode('utf-8'))
            if 'agent.json' in documents:
                config = json.loads(documents['agent.json'])
                if not isinstance(config, dict):
                    raise ValueError('agent.json must contain a JSON object')
                allowed = {'name', 'description', 'handoff_description', 'system_prompt', 'task_prompt', 'model', 'reasoning',
                           'tools', 'tool_groups', 'tool_names', 'include_all_tools', 'handoffs', 'handoff_names', 'context', 'skills', 'playbooks'}
                if set(config) - allowed:
                    raise ValueError('Unsupported agent.json keys: ' + ', '.join(sorted(set(config) - allowed)))
                for key in ('model', 'reasoning', 'name', 'description', 'handoff_description', 'system_prompt', 'task_prompt'):
                    if config.get(key) is not None and not isinstance(config[key], str):
                        raise ValueError(key + ' must be text')
                if isinstance(config.get('tools'), dict) and set(config['tools']) - {'groups', 'names', 'allow', 'include_all', 'all'}:
                    raise ValueError('Unsupported tools configuration')
            spec = load_assistant_spec(directory, root_dir=root)
            if spec.name != name:
                raise ValueError('Assistant identity changes require the lifecycle CLI')
            specs.append(replace(spec, path=f'app/backend/src/domain/assistant_specs/{name}/system.md'))
    registry = AssistantRegistry(specs)
    configure_tools(registry)
    registry.validate()
    registry.source_files = {name: dict(documents) for name, documents in files.items()}
    return registry


def capture(registry: AssistantRegistry, names: list[str] | None = None) -> dict:
    """Freeze definitions and resolved model defaults, independently of code/data."""
    specs = {name: {**asdict(registry.get_spec(name)), 'resolved_model': registry.get_spec(name).resolved_model()}
             for name in (names or registry.list_assistants())}
    value = json.loads(json.dumps({'version': 1, 'specs': specs}))
    return {**value, 'hash': digest(value)}


def registry_from_capture(graph: dict) -> AssistantRegistry:
    """Restore a versioned graph, checking identity and its immutable hash."""
    if graph.get('version') != 1 or digest({key: graph[key] for key in ('version', 'specs')}) != graph.get('hash'):
        raise ValueError('Invalid captured assistant graph')
    specs = []
    for name, definition in graph['specs'].items():
        config = {key: value for key, value in definition.items() if key != 'resolved_model'}
        # Older graphs predate playbooks; preserve their original capabilities.
        config.setdefault('playbook_names', ())
        for key in ('tool_group_keys', 'tool_names', 'handoff_names', 'skill_names', 'playbook_names'):
            if config.get(key) is not None:
                config[key] = tuple(config[key])
        spec = AssistantSpec(**config)
        if name != spec.name or not definition.get('resolved_model'):
            raise ValueError('Invalid captured assistant identity or model')
        specs.append(spec)
    registry = AssistantRegistry(specs)
    configure_tools(registry)
    registry.resolved_models = {name: definition['resolved_model'] for name, definition in graph['specs'].items()}
    registry.validate()
    return registry
