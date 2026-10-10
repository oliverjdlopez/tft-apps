"""Bounded local trials with durable receipts independent of Langfuse."""
from __future__ import annotations

import threading
import uuid

from common.assistant_workspace import checkout_lock

slots = threading.BoundedSemaphore(4)


class CapacityError(ValueError):
    """Signal that all four trial subprocess slots are already occupied."""


def start(workspace, name: str, question: str, **expected) -> dict:
    """Persist one trial before starting a browser-independent bounded worker."""
    if not question.strip():
        raise ValueError('Enter a question for the trial')
    with checkout_lock(workspace.store.root):
        active, draft, head = workspace.graphs(name, name, **expected)
        with workspace.store.connect() as db:
            count = db.execute("SELECT count(*) FROM runs WHERE kind='trial' AND state IN ('queued','running')").fetchone()[0]
        if count >= 4 or not slots.acquire(blocking=False):
            raise CapacityError('Four trials are active; retry after one finishes')
        identity = uuid.uuid4().hex
        lineage = {'draft_revision': head['id'], 'draft_content_hash': head['content_hash'],
                   'active_graph_hash': active['hash'], 'active_registry_hash': expected['expected_active'], 'draft_graph_hash': draft['hash']}
        value = {'question': question, 'active_graph': active, 'draft_graph': draft, 'lineage': lineage}
        try:
            receipt = workspace.store.put_run(identity, name, head['id'], 'trial', 'queued', value)
        except BaseException:
            slots.release()
            raise
    thread = threading.Thread(target=execute, args=(workspace.store, receipt), daemon=True, name='specs-trial-' + identity)
    try:
        thread.start()
    except BaseException:
        slots.release()
        workspace.store.put_run(identity, name, head['id'], 'trial', 'failed', {**value, 'error': 'Unable to start trial worker'})
        raise
    return receipt


def execute(store, receipt: dict) -> None:
    """Retain execution results after disconnects and always release capacity."""
    from evals.utils import isolated_operation
    from evals.langfuse.server import ExperimentService
    identity, name, revision = receipt['id'], receipt['assistant'], receipt['revision']
    value = receipt['value']
    try:
        store.put_run(identity, name, revision, 'trial', 'running', value)
        provenance = ExperimentService.provenance(None)
        payload = {'operation': 'evaluate', 'config': {'family': 'assistant', 'assistant': name,
            'max_turns': 10, 'workspace_trial': True, 'captured_graph': value['draft_graph'],
            'workspace_lineage': value['lineage']}, 'input': {'input': value['question']},
            'identity': {'suite': 'specs-trial', 'case': identity}}
        result = isolated_operation(payload, 180)
        store.put_run(identity, name, revision, 'trial', 'failed' if result.get('error') else 'completed',
                      {**value, 'result': result, 'provenance': provenance})
    except Exception as exc:
        store.put_run(identity, name, revision, 'trial', 'failed', {**value, 'error': f'{type(exc).__name__}: {exc}'})
    finally:
        slots.release()
