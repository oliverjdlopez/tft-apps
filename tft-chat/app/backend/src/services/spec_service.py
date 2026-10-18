"""Public Specs facade for read-only documents and the assistant workspace."""
from __future__ import annotations

import hashlib
from pathlib import Path

from domain.assistants import ASSISTANT_SPECS_DIR
from dev.assistants.workspace.workspace import (
    ConflictError as DocumentConflictError,
    Workspace,
)
from evals.config import load_eval_suites

REPO_ROOT = Path(__file__).resolve().parents[4]
EDITABLE_FILES = ('system.md', 'agent.json', 'task.md')


def workspace_service() -> Workspace:
    """Bind each operation to this checkout's cached runtime and ignored store."""
    return Workspace(REPO_ROOT, ASSISTANT_SPECS_DIR)


def initialize_workspace() -> None:
    """Recover authoring state before publishing live assistant definitions."""
    workspace_service().initialize()


def workspace() -> dict:
    """List cached assistant definitions and allowlisted document identities."""
    service = workspace_service()
    suites = {}
    for suite in load_eval_suites():
        suites.setdefault(suite.assistant, []).append(suite.name)
    active = service.active()
    assistants = []
    for name in active.registry.assistant_names:
        spec = active.registry.get_spec(name)
        assistants.append({'name': name, 'description': spec.description, 'model': spec.resolved_model(),
            'tools': list(spec.tool_names), 'tool_groups': list(spec.tool_group_keys), 'handoffs': list(spec.handoff_names),
            'eval_suites': suites.get(name, []), 'sources': [{'document_id': hashlib.sha256(f'spec\0{name}\0{filename}'.encode()).hexdigest()[:24],
                'label': filename, 'path': f'app/backend/src/domain/assistant_specs/{name}/{filename}'}
                for filename in EDITABLE_FILES if filename in active.source_files.get(name, {})]})
    return {'assistants': assistants}


def read_document(document_id: str) -> dict:
    """Keep the legacy read interface for source inspection, never mutation."""
    for assistant in workspace()['assistants']:
        for source in assistant['sources']:
            if source['document_id'] == document_id:
                path = ASSISTANT_SPECS_DIR / assistant['name'] / source['label']
                if path.is_symlink() or path.parent.is_symlink():
                    raise ValueError('Symlinked assistant documents cannot be read')
                path.resolve().relative_to(ASSISTANT_SPECS_DIR.resolve())
                content = path.read_bytes().decode('utf-8')
                return {'id': document_id, 'assistant': assistant['name'], 'label': source['label'], 'path': source['path'],
                    'language': 'json' if source['label'].endswith('.json') else 'markdown', 'content': content,
                    'revision': hashlib.sha256(content.encode()).hexdigest(), 'test_suites': assistant['eval_suites']}
    raise KeyError(document_id)


def save_document(*args, **kwargs):
    """Reject legacy writes so source changes cannot bypass draft validation/apply."""
    raise ValueError('Direct document writes are retired. Save an assistant draft through /api/specs/assistants/{name}/draft and Apply it explicitly.')
