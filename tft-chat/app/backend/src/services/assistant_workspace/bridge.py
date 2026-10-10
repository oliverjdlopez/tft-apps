"""Server-side authenticated bridge to this checkout's host experiment runner."""
from __future__ import annotations

import httpx
from common.assistant_workspace import checkout_lock


class UnavailableError(ValueError):
    """Report optional experiment service unavailability without leaking secrets."""


def request(workspace, method: str, path: str, payload: dict | None = None) -> dict:
    """Call the allowlisted checkout Unix socket with backend-only credentials."""
    from dotenv import dotenv_values
    root = workspace.root / 'evals' / 'langfuse'
    token = dotenv_values(root / '.env').get('LANGFUSE_EXPERIMENT_TOKEN')
    socket = root / '.runtime' / 'runner.sock'
    if not token or not socket.exists():
        raise UnavailableError('Langfuse experiments are unavailable. Start this checkout with python -m evals up; drafts and Apply remain available.')
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(socket)), base_url='http://runner', timeout=60,
                          headers={'Authorization': 'Bearer ' + token}) as client:
            response = client.request(method, path, json=payload)
            if response.status_code >= 400:
                detail = response.json().get('detail', 'Unable to prepare experiment')
                raise UnavailableError(str(detail))
            return response.json()
    except (httpx.HTTPError, OSError):
        raise UnavailableError('The checkout experiment runner is unreachable. Start Langfuse and retry with the same submission identifier.') from None


def datasets(workspace, name: str) -> dict:
    """Offer only registered live workflows reachable in the active/draft graph."""
    from domain.assistants.capture import reachable, registry_from_files
    active = workspace.active()
    head = workspace.store.head(name)
    draft = registry_from_files({**active.source_files, name: head['files']}) if head and workspace.validate(name, head['files'])['valid'] else active
    result = request(workspace, 'GET', '/workspace/datasets')
    result['datasets'] = [row for row in result['datasets'] if name in set(reachable(active, row['assistant'])) | set(reachable(draft, row['assistant']))]
    return result


def submit(workspace, name: str, submission_id: str, dataset: str, cases: list[str], repetitions: int, **expected) -> dict:
    """Persist intent, then contact the optional runner outside the checkout lock."""
    prior = workspace.store.run(submission_id)
    selected = None
    if prior is None:
        options = datasets(workspace, name)['datasets']
        selected = next((row for row in options if row['name'] == dataset), None)
        if selected is None:
            raise ValueError('Choose an eligible registered live dataset')
    with checkout_lock(workspace.store.root):
        prior = workspace.store.run(submission_id)
        if prior:
            if prior['assistant'] != name or prior['revision'] != expected['expected_draft'] or prior['value']['selection'] != {'dataset': dataset, 'cases': cases, 'repetitions': repetitions}:
                raise ValueError('Submission identifier belongs to another request')
            if prior['value'].get('receipt') or prior['state'] == 'failed':
                return prior
            payload, value, revision = prior['value']['payload'], prior['value'], prior['revision']
        else:
            active, draft, head = workspace.graphs(name, selected['assistant'], **expected)
            lineage = {'draft_revision': head['id'], 'draft_content_hash': head['content_hash'],
                'active_graph_hash': active['hash'], 'active_registry_hash': expected['expected_active'],
                'draft_graph_hash': draft['hash'], 'assistant': name}
            payload = {'submission_id': submission_id, 'dataset': dataset, 'cases': cases, 'repetitions': repetitions,
                       'active_graph': active, 'draft_graph': draft, 'lineage': lineage}
            revision = head['id']
            value = {'payload': payload, 'lineage': lineage, 'selection': {'dataset': dataset, 'cases': cases, 'repetitions': repetitions}}
            workspace.store.put_run(submission_id, name, revision, 'experiment', 'preparing', value)
    # Optional service delays must not prevent another browser from saving or
    # applying a draft. The host's durable key serializes concurrent submissions.
    try:
        receipt = request(workspace, 'POST', '/workspace/experiments', payload)
        value.pop('error', None)
        with checkout_lock(workspace.store.root):
            return workspace.store.put_run(submission_id, name, revision, 'experiment', receipt.get('state', 'queued'), {**value, 'receipt': receipt})
    except UnavailableError as exc:
        with checkout_lock(workspace.store.root):
            current = workspace.store.run(submission_id)
            if current['value'].get('receipt'):
                return current
            return workspace.store.put_run(submission_id, name, revision, 'experiment', 'preparing', {**value, 'error': str(exc)})


def status(workspace, identity: str) -> dict:
    """Refresh a receipt without changing its originally captured revision."""
    run = workspace.store.run(identity)
    if run is None:
        raise KeyError(identity)
    if run['kind'] == 'experiment' and run['value'].get('receipt', {}).get('job_id'):
        job = request(workspace, 'GET', '/jobs/' + run['value']['receipt']['job_id'])
        run = workspace.store.put_run(identity, run['assistant'], run['revision'], run['kind'], job['state'], {**run['value'], 'job': job})
    return run


def import_prompt(workspace, name: str, prompt: str, version: int, **expected) -> dict:
    """Resolve an owned concrete prompt version and save it as a local draft."""
    result = request(workspace, 'POST', '/workspace/import', {'assistant': name, 'prompt': prompt, 'version': version})
    active, head, _ = workspace.check(name, **expected)
    files = dict(head['files'] if head else active.source_files[name])
    files['system.md'] = result['text']
    if 'agent.json' in files:
        import json
        try:
            config = json.loads(files['agent.json'])
        except ValueError:
            config = None
        if isinstance(config, dict) and 'system_prompt' in config:
            # An inline base override would otherwise mask the imported text.
            config.pop('system_prompt')
            files['agent.json'] = json.dumps(config, indent=2) + '\n'
    return workspace.save(name, files, provenance={'langfuse': result}, **expected)
