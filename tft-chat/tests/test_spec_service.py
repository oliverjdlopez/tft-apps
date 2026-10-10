"""Draft lifecycle and recoverable apply acceptance checks without model calls."""
from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain.assistants.capture import capture, registry_from_files
from services.assistant_workspace.workspace import ConflictError, Workspace
from services import spec_service


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    """Use a separate specification tree, registry, and ignored SQLite store."""
    specs = tmp_path / 'assistant_specs'
    files = {'fixture': {'system.md': '# Fixture\nOriginal prompt.\n', 'agent.json': '{"name":"fixture","skills":[]}'},
             'target': {'system.md': '# Target\nOriginal target.\n'}}
    for name, documents in files.items():
        directory = specs / name
        directory.mkdir(parents=True)
        for filename, content in documents.items():
            (directory / filename).write_bytes(content.encode())
    (specs / 'fixture' / 'notes.md').write_text('Unrelated user notes\n')
    return Workspace(tmp_path, specs, registry_from_files(files))


def expected(state: dict) -> dict:
    """Return the three identities sent by a revision-aware browser mutation."""
    return {'expected_draft': state['draft']['id'] if state['draft'] else None,
            'expected_active': state['active']['hash'], 'expected_source': state['source_hash']}


def save(workspace: Workspace, **changes) -> dict:
    """Save one fixture assistant with optional replacement editable files."""
    state = workspace.state('fixture')
    files = {**(state['draft']['files'] if state['draft'] else state['active']['files']), **changes}
    return workspace.save('fixture', files, **expected(state))


def test_save_does_not_write_source_and_revisions_survive_restart(workspace):
    """Invalid saves remain editable and earlier contents are immutable."""
    original = workspace.source_files()
    first = save(workspace, **{'system.md': 'Changed instructions', 'agent.json': '[]'})
    assert first['validation']['valid'] is False
    assert workspace.source_files() == original
    restarted = Workspace(workspace.root, workspace.specs, workspace.registry)
    assert restarted.state('fixture')['draft']['id'] == first['draft']['id']
    fixed = save(restarted, **{'agent.json': '{}'})
    assert fixed['validation']['valid']
    assert restarted.store.revision(first['draft']['id'])['files']['agent.json'] == '[]'
    assert len(fixed['history']['revisions']) == 2
    with pytest.raises(ConflictError, match='draft changed'):
        restarted.save('fixture', first['draft']['files'], **expected(first))


def test_apply_complete_optional_files_and_existing_graph_remains_captured(workspace):
    """Apply changes all editable files, retains unrelated files and old agents."""
    from domain.assistants import create_assistant
    old = create_assistant('fixture', registry=workspace.active())
    state = save(workspace, **{'system.md': 'New prompt', 'agent.json': '{"handoffs":["target"],"skills":[]}', 'task.md': 'Task wrapper'})
    before = workspace.state('fixture')['active']['hash']
    applied = workspace.apply('fixture', **expected(state))
    assert applied['draft'] is None
    assert applied['active']['hash'] != before
    assert applied['active']['configuration']['handoff_names'] == ['target']
    assert applied['active']['configuration']['task_prompt'] == 'Task wrapper'
    from agents import RunContextWrapper
    assert 'Original prompt.' in old.instructions(RunContextWrapper(None), old)
    assert old.handoffs == []
    assert (workspace.specs / 'fixture' / 'notes.md').read_text() == 'Unrelated user notes\n'
    assert applied['history']['events'][0]['action'] == 'applied'
    files = {'system.md': 'Third prompt'}
    saved = workspace.save('fixture', files, **expected(applied))
    workspace.apply('fixture', **expected(saved))
    assert not (workspace.specs / 'fixture' / 'agent.json').exists()
    assert not (workspace.specs / 'fixture' / 'task.md').exists()


def test_source_and_runtime_conflicts_keep_draft_and_user_edits(workspace):
    """Both optimistic identities and the draft's original base prevent overwrite."""
    state = save(workspace, **{'system.md': 'Draft prompt'})
    (workspace.specs / 'target' / 'system.md').write_text('External target edit')
    with pytest.raises(ConflictError, match='Repository files changed'):
        workspace.apply('fixture', **expected(state))
    current = workspace.state('fixture')
    assert current['source_changed']
    workspace.refresh(current['active']['hash'], current['source_hash'])
    with pytest.raises(ConflictError, match='Active definitions changed'):
        workspace.apply('fixture', **expected(state))
    current = workspace.state('fixture')
    with pytest.raises(ConflictError, match='older definitions'):
        workspace.apply('fixture', **expected(current))
    restored = workspace.restore('fixture', state['draft']['id'], **expected(current))
    workspace.apply('fixture', **expected(restored))
    assert (workspace.specs / 'target' / 'system.md').read_text() == 'External target edit'


def test_discard_restore_and_captured_handoffs(workspace):
    """Discard retains history; restore creates a new identity and union graph."""
    state = save(workspace, **{'agent.json': '{"handoffs":["target"]}'})
    active, draft, _ = workspace.graphs('fixture', 'fixture', **expected(state))
    assert set(active['specs']) == set(draft['specs']) == {'fixture', 'target'}
    (workspace.specs / 'target' / 'system.md').write_text('Later repository edit')
    assert draft['specs']['target']['system_prompt'] == 'Original target.' or 'Original target.' in draft['specs']['target']['system_prompt']
    current = workspace.state('fixture')
    discarded = workspace.discard('fixture', **expected(current))
    restored = workspace.restore('fixture', state['draft']['id'], **expected(discarded))
    assert restored['draft']['id'] != state['draft']['id']
    assert restored['draft']['provenance']['restored_from'] == state['draft']['id']


@pytest.mark.parametrize('config,error', [('{"handoffs":["absent"]}', 'Unknown assistant'),
    ('{"handoffs":["fixture"]}', 'cycle'), ('{"tools":["absent"]}', 'Unknown'),
    ('{"name":"renamed"}', 'identity'), ('{"model":"missing-model"}', 'model must be'),
    ('{"context":{"repository":"yes"}}', 'boolean')])
def test_invalid_graph_saved_but_cannot_apply_or_test(workspace, config, error):
    """Draft execution cannot bypass tools, identity, model, or graph validation."""
    state = save(workspace, **{'agent.json': config})
    assert not state['validation']['valid']
    with pytest.raises((ValueError, KeyError)):
        workspace.apply('fixture', **expected(state))
    with pytest.raises((ValueError, KeyError)):
        workspace.graphs('fixture', 'fixture', **expected(state))


def test_write_failure_rolls_back_complete_source_and_keeps_draft(workspace, monkeypatch):
    """A failure between editable file writes restores original bytes."""
    from services.assistant_workspace import workspace as module
    original = workspace.source_files()
    state = save(workspace, **{'system.md': 'Updated', 'task.md': 'New task'})
    real = module.atomic_bytes
    def fail(path, data):
        """Fail only one apply write, allowing the recovery implementation to run."""
        if path.name == 'task.md':
            raise OSError('simulated write failure')
        return real(path, data)
    monkeypatch.setattr(module, 'atomic_bytes', fail)
    with pytest.raises(OSError, match='simulated'):
        workspace.apply('fixture', **expected(state))
    assert workspace.source_files() == original
    assert workspace.store.head('fixture')['id'] == state['draft']['id']
    assert not (workspace.store.root / 'apply-journal.json').exists()


def test_restart_recovers_journal_before_discovery_and_preserves_external_edits(workspace):
    """Recovery checks all bytes before rollback and refuses unrelated edits."""
    from common.assistant_workspace import recover
    path = workspace.specs / 'fixture' / 'system.md'
    old = path.read_bytes()
    journal = {'assistant': 'fixture', 'changes': {'system.md': [base64.b64encode(old).decode(), base64.b64encode(b'Partial write').decode()]}}
    target = workspace.store.root / 'apply-journal.json'
    target.write_text(json.dumps(journal))
    path.write_bytes(b'Partial write')
    recover(workspace.store.root, workspace.specs)
    assert path.read_bytes() == old
    target.write_text(json.dumps(journal))
    path.write_bytes(b'External edit after crash')
    with pytest.raises(ValueError, match='external edit'):
        recover(workspace.store.root, workspace.specs)
    assert path.read_bytes() == b'External edit after crash'
    assert target.exists()


def test_routes_retire_direct_writes_and_support_full_lifecycle(workspace, monkeypatch):
    """The browser route boundary never bypasses drafts or optimistic conflicts."""
    from app.backend.api.app import create_app
    monkeypatch.setattr(spec_service, 'workspace_service', lambda: workspace)
    client = TestClient(create_app())
    state = client.get('/api/specs/assistants/fixture').json()
    payload = {**expected(state), 'files': {'system.md': 'Browser draft'}}
    saved = client.post('/api/specs/assistants/fixture/draft', json=payload)
    assert saved.status_code == 200
    assert client.post('/api/specs/assistants/fixture/draft', json=payload).status_code == 409
    assert client.put('/api/specs/documents/old', json={'content': 'Bypass', 'revision': 'a' * 64}).status_code == 410
    assert client.post('/api/specs/assistants/fixture/apply', json=expected(saved.json())).status_code == 200


def test_committed_restart_finishes_history_and_closes_draft_once(workspace):
    """A crash after source commit can finish store updates without reapplying files."""
    from common.assistant_workspace import recover
    state = save(workspace, **{'system.md': 'Committed source'})
    path = workspace.specs / 'fixture' / 'system.md'
    path.write_text('Committed source')
    journal = {'id': 'committed-operation', 'assistant': 'fixture', 'revision': state['draft']['id'], 'created': 1, 'committed': True, 'changes': {}}
    (workspace.store.root / 'apply-journal.json').write_text(json.dumps(journal))
    recover(workspace.store.root, workspace.specs)
    assert workspace.store.head('fixture') is None
    assert path.read_text() == 'Committed source'
    assert workspace.store.history('fixture')['events'][0]['action'] == 'applied'
    recover(workspace.store.root, workspace.specs)
    assert len(workspace.store.history('fixture')['events']) == 1
