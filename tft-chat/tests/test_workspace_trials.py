"""Browser-independent local trial execution, interruptions, and optional bridge."""
from __future__ import annotations

import time

from services.assistant_workspace import trials, bridge
from tests.test_spec_service import workspace, expected, save


def test_trial_uses_saved_graph_without_langfuse(workspace, monkeypatch):
    """A local worker executes the saved revision and persists usage/output."""
    from evals import utils
    payloads = []
    def isolated(payload, timeout):
        """Return a deterministic worker result without networking or model calls."""
        payloads.append((payload, timeout))
        return {'output': 'Mock trial answer', 'token_usage': {'total': 12}, 'metadata': {'database': 'workspace_test'}}
    monkeypatch.setattr(utils, 'isolated_operation', isolated)
    monkeypatch.setattr(bridge, 'request', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('Langfuse should not be called')))
    state = save(workspace, **{'system.md': 'Trial instructions', 'task.md': 'Use wrapper'})
    receipt = trials.start(workspace, 'fixture', 'Question', **expected(state))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = workspace.store.run(receipt['id'])
        if result['state'] in {'failed', 'completed'}:
            break
        time.sleep(.01)
    assert result['state'] == 'completed'
    assert result['value']['result']['output'] == 'Mock trial answer'
    payload, timeout = payloads[0]
    assert timeout == 180 and payload['config']['max_turns'] == 10
    assert payload['config']['workspace_trial']
    assert payload['config']['captured_graph']['specs']['fixture']['task_prompt'] == 'Use wrapper'
    assert receipt['revision'] == state['draft']['id']


def test_restart_marks_trials_interrupted_and_preserves_results(workspace):
    """Restart never silently retries queued/running paid model operations."""
    workspace.store.put_run('running', 'fixture', 'revision', 'trial', 'running', {'question': 'Question'})
    workspace.store.put_run('completed', 'fixture', 'revision', 'trial', 'completed', {'result': {'output': 'Saved'}})
    workspace.store.interrupt_trials()
    assert workspace.store.run('running')['state'] == 'interrupted'
    assert workspace.store.run('completed')['value']['result']['output'] == 'Saved'


def test_import_creates_local_draft_with_provenance(workspace, monkeypatch):
    """Import only resolves remote content and never applies automatically."""
    monkeypatch.setattr(bridge, 'request', lambda *args: {'text': 'Imported version', 'name': 'chattft/assistants/fixture', 'version': 3})
    state = workspace.state('fixture')
    result = bridge.import_prompt(workspace, 'fixture', 'chattft/assistants/fixture', 3, **expected(state))
    assert result['draft']['files']['system.md'] == 'Imported version'
    assert result['draft']['provenance']['langfuse']['version'] == 3
    assert 'Original prompt' in result['active']['instructions']


def test_trial_capacity_is_checkout_bounded(workspace):
    """Durable active receipts enforce capacity even across backend instances."""
    import pytest
    state = save(workspace)
    for index in range(4):
        workspace.store.put_run(str(index), 'fixture', state['draft']['id'], 'trial', 'running', {})
    with pytest.raises(trials.CapacityError):
        trials.start(workspace, 'fixture', 'Question', **expected(state))
    assert len(workspace.store.runs('fixture')) == 4


def test_uncertain_experiment_reply_reuses_persisted_graphs_and_submission(workspace, monkeypatch):
    """A later retry recovers the same remote job without refreezing definitions."""
    state = save(workspace)
    calls = []
    monkeypatch.setattr(bridge, 'datasets', lambda *args: {'datasets': [{'name': 'fixture', 'assistant': 'fixture'}]})
    def request(service, method, path, payload=None):
        """Simulate a lost acknowledgement after the remote runner accepts it."""
        calls.append(payload)
        if len(calls) == 1:
            raise bridge.UnavailableError('Response lost')
        return {'state': 'queued', 'job_id': 'accepted-once', 'snapshot': 'exact-snapshot'}
    monkeypatch.setattr(bridge, 'request', request)
    options = {'submission_id': 'uncertain-submission-123', 'dataset': 'fixture', 'cases': [], 'repetitions': 1, **expected(state)}
    first = bridge.submit(workspace, 'fixture', **options)
    assert first['state'] == 'preparing'
    (workspace.specs / 'target' / 'system.md').write_text('Later repository edit')
    second = bridge.submit(workspace, 'fixture', **options)
    assert second['state'] == 'queued'
    assert calls[0] == calls[1]
    assert second['value']['receipt']['job_id'] == 'accepted-once'
    assert bridge.submit(workspace, 'fixture', **options)['id'] == second['id']
    assert len(calls) == 2
