"""Captured assistant comparisons on the existing durable Langfuse runner."""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from common.assistant_workspace import checkout_lock
from domain.assistants.capture import capture, digest, from_capture, reachable, registry_from_files
from .content import fetch_bundle, load_catalog, load_snapshot, validate_bundle
from .utils import atomic_write, canonical_json, content_hash, is_not_found, resolved_prompt

router = APIRouter(prefix='/workspace')


class ComparisonRequest(BaseModel):
    """Captured Active/Draft graphs and immutable local workspace lineage."""
    model_config = ConfigDict(extra='forbid')
    submission_id: str = Field(min_length=16, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')
    dataset: str
    cases: list[str] = Field(default_factory=list)
    repetitions: int = Field(default=1, ge=1, le=20)
    active_graph: dict[str, Any]
    draft_graph: dict[str, Any]
    lineage: dict[str, Any]


class ImportRequest(BaseModel):
    """Concrete owned prompt identity to resolve on the authenticated host."""
    model_config = ConfigDict(extra='forbid')
    assistant: str = Field(pattern=r'^[A-Za-z0-9_-]+$')
    prompt: str
    version: int = Field(ge=1)


def registered_datasets(service, *, live: bool = True) -> list[dict]:
    """Read registered live dataset routing and active hosted case identities."""
    from .contracts import ACTIVE_WORKFLOW_SUITES, DATASET_NAMES
    result = []
    for entry in load_catalog(service.snapshots):
        if entry['family'] != 'assistant' or entry['execution'] != 'live':
            continue
        if entry['name'] not in ACTIVE_WORKFLOW_SUITES and not entry.get('managed_workflow'):
            continue
        baseline = load_snapshot(entry['snapshot'], service.snapshots)
        name = baseline['dataset_name'] if entry.get('managed_workflow') else DATASET_NAMES[entry['name']]
        row = {'name': name, 'assistant': entry['assistant'], 'suite': entry['name'], 'cases': []}
        if live:
            dataset = service.client.get_dataset(name)
            row['id'] = dataset.id
            row['cases'] = [{'id': (item.metadata or {}).get('case_id', f"{entry['name']}/{item.id}"),
                             'input': item.input} for item in dataset.items
                            if str(item.status).upper().split('.')[-1] == 'ACTIVE']
        result.append(row)
    return result


def current_execution(suite: dict, variants: list[dict]) -> dict:
    """Freeze current repository configuration for fresh native assistant runs."""
    from domain.assistants.specs import ASSISTANT_SPECS_DIR, ROOT_DIR
    from services.assistant_workspace.workspace import Workspace
    workspace = Workspace(ROOT_DIR, ASSISTANT_SPECS_DIR)
    registry = registry_from_files(workspace.source_files())
    names = sorted(set(reachable(registry, suite['assistant'])) | {target for target in ('context_selector', 'skill_selector') if target in registry.list_assistants()})
    graph = capture(registry, names)
    return {'version': 1, 'graphs': {variant['name']: deepcopy(graph) for variant in variants},
            'lineage': {'origin': 'repository', 'active_graph_hash': graph['hash']}}


def publish_graph_prompts(client, graph: dict) -> dict:
    """Publish instruction copies with captured configuration; pin exact versions."""
    result = {}
    for assistant, definition in graph['specs'].items():
        # Configuration is part of version identity even when instructions match.
        specification_hash = digest(definition)
        name = f'chattft/workspace/{assistant}/{specification_hash}'
        try:
            prompt = resolved_prompt(client, {'name': name, 'label': 'latest'})
            if prompt['text'] != definition['system_prompt']:
                raise ValueError('Managed prompt identity has different instruction bytes')
        except Exception as exc:
            if not is_not_found(exc):
                raise
            created = client.create_prompt(name=name, type='text', prompt=definition['system_prompt'],
                config={'assistant': assistant, 'specification_hash': specification_hash, 'specification': definition}, labels=[])
            prompt = ({'name': created.name, 'version': created.version, 'text': definition['system_prompt']}
                      if created is not None else resolved_prompt(client, {'name': name, 'label': 'latest'}))
        result[assistant] = prompt
    return result


def submit_comparison(service, body: ComparisonRequest) -> dict:
    """Prepare once, preserving uncertain replies and explicit preparation failures."""
    payload = body.model_dump()
    request_hash = digest(payload)
    with checkout_lock(service.runtime / 'workspace-submissions'):
        prior = service.jobs.submission(body.submission_id)
        if prior:
            if prior['request_hash'] != request_hash:
                raise ValueError('Submission identifier was reused for different contents')
            if prior.get('state') == 'preparing':
                value = {'state': 'interrupted', 'error': 'Preparation was interrupted; create a new submission explicitly'}
                service.jobs.put_submission(body.submission_id, request_hash, value)
                return value
            return {key: value for key, value in prior.items() if key != 'request_hash'}
        service.jobs.put_submission(body.submission_id, request_hash, {'state': 'preparing'})
        try:
            selected = next((row for row in registered_datasets(service, live=False) if row['name'] == body.dataset), None)
            if selected is None:
                raise ValueError('Unknown registered live assistant dataset')
            active, draft = from_capture(body.active_graph), from_capture(body.draft_graph)
            name = body.lineage.get('assistant')
            if body.lineage.get('active_graph_hash') != body.active_graph['hash'] or body.lineage.get('draft_graph_hash') != body.draft_graph['hash']:
                raise ValueError('Graph lineage does not match captured definitions')
            if name not in set(reachable(active, selected['assistant'])) | set(reachable(draft, selected['assistant'])):
                raise ValueError('Edited assistant is unreachable from this workflow')
            if set(body.active_graph['specs']) != set(body.draft_graph['specs']) or any(
                    body.active_graph['specs'][key] != body.draft_graph['specs'][key]
                    for key in body.active_graph['specs'] if key != name):
                raise ValueError('Only the selected assistant may differ between Active and Draft')
            execution = {'version': 1, 'graphs': {'Active': body.active_graph, 'Draft': body.draft_graph},
                         'lineage': {**body.lineage, 'submission_id': body.submission_id}}
            config = {'variants': [{'name': 'Active', 'prompts': {}}, {'name': 'Draft', 'prompts': {}}],
                      'cases': body.cases, 'repetitions': body.repetitions, 'concurrency': 4}
            bundle = fetch_bundle(service.client, body.dataset, config, service.snapshots, captured_execution=execution)
            selected_cases = set(body.cases)
            if not any(item.get('status', 'ACTIVE') == 'ACTIVE' and (not selected_cases or item['id'] in selected_cases) for item in bundle['items']):
                raise ValueError('No active dataset cases selected; no experiment was scheduled')
            bundle['provenance'] = service.provenance()
            bundle = validate_bundle(bundle)
            # Workspace runs retain immutable artifacts without replacing the
            # dataset catalogue's authoring/routing snapshot.
            data = canonical_json(bundle)
            snapshot = content_hash(data)
            path = service.snapshots / (snapshot + '.json')
            if path.exists() and path.read_bytes() != data:
                raise ValueError('Immutable snapshot was modified')
            atomic_write(path, data)
            bundle['snapshot_id'] = snapshot
            job_id = service.jobs.submit(bundle, snapshot, submission_id=body.submission_id)
            service.wakeup.set()
            return {'state': 'queued', 'job_id': job_id, 'snapshot': snapshot, 'status_url': '/jobs/' + job_id}
        except Exception as exc:
            value = {'state': 'failed', 'error': f'Preparation failed: {exc}' if isinstance(exc, ValueError) else f'Preparation failed ({type(exc).__name__}); inspect the checkout runner logs'}
            service.jobs.put_submission(body.submission_id, request_hash, value)
            return value


@router.get('/datasets')
def datasets(request: Request) -> dict:
    """Discover registered live assistant datasets through authenticated access."""
    try:
        return {'available': True, 'datasets': registered_datasets(request.app.state.service)}
    except Exception:
        raise HTTPException(503, 'Unable to read Langfuse datasets; inspect the checkout runner logs') from None


@router.post('/experiments', status_code=202)
def experiment(request: Request, body: ComparisonRequest) -> dict:
    """Queue or return the existing receipt for a captured comparison."""
    try:
        return submit_comparison(request.app.state.service, body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get('/prompts/{assistant}')
def prompts(request: Request, assistant: str) -> dict:
    """List only owned assistant prompts and their concrete versions."""
    from .utils import configured_workspace
    if not re.fullmatch(r'[A-Za-z0-9_-]+', assistant):
        raise HTTPException(400, 'Invalid assistant identity')
    workspace = configured_workspace()
    try:
        owned = [row for row in workspace.list('v2/prompts') if row['name'] == f'chattft/assistants/{assistant}' or row['name'].startswith(f'chattft/workspace/{assistant}/')]
        return {'prompts': [{'name': row['name'], 'versions': row['versions']} for row in owned]}
    finally:
        workspace.close()


@router.post('/import')
def import_prompt(request: Request, body: ImportRequest) -> dict:
    """Resolve text from an owned assistant prompt without applying it."""
    if body.prompt != f'chattft/assistants/{body.assistant}' and not body.prompt.startswith(f'chattft/workspace/{body.assistant}/'):
        raise HTTPException(400, 'Choose an owned prompt for this assistant')
    try:
        return resolved_prompt(request.app.state.service.client, {'name': body.prompt, 'version': body.version})
    except Exception:
        raise HTTPException(503, 'Unable to resolve the selected concrete prompt version') from None
