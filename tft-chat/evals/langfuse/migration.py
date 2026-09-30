"""Resumable native dataset migration with identity and content verification."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import quote
from domain.assistants.constants import AssistantName

from .contracts import DATASET_NAMES, dataset_schemas, migrate_item, validate_natural_item
from .utils import atomic_write, canonical_json, content_hash


def plan_migration(backup: dict, suites: dict, *, available_skills: set[str]) -> dict:
    """Build a reviewable rollback mapping from live content, including UI additions."""
    plan = {'version': 1, 'backup_sha256': content_hash(canonical_json(backup)), 'datasets': [], 'assertions': []}
    for dataset in backup['datasets']:
        alias = next((key for key, name in DATASET_NAMES.items()
                      if dataset['name'] in {name, f'chattft/{key}'}), None)
        if alias is None:
            continue
        suite = suites[alias]
        change = {'id': dataset['id'], 'old_name': dataset['name'], 'name': DATASET_NAMES[alias],
                  'suite': suite, 'schemas': dataset_schemas(suite), 'items': [],
                  'original_dataset': {k: v for k, v in dataset.items() if k != 'items'}}
        for remote in dataset['items']:
            metadata = deepcopy(remote.get('metadata') or {})
            case_id = metadata.setdefault('case_id', f"{alias}/{remote['id']}")
            metadata.setdefault('case', case_id.split('/', 1)[-1])
            metadata.setdefault('suite', alias)
            local = {'id': case_id, 'remote_id': remote['id'], 'input': remote['input'],
                     'expected_output': remote['expectedOutput'], 'metadata': metadata,
                     'status': remote['status']}
            converted, mappings = migrate_item(suite, local, available_skills=available_skills)
            validate_natural_item(suite, converted)
            change['items'].append({'original': remote, 'converted': converted})
            plan['assertions'].extend(mappings)
        plan['datasets'].append(change)
    return plan


def apply_migration(workspace, native, plan: dict, journal_path: Path) -> dict:
    """Apply a pre-exported plan with stable IDs and conflict checks on every item.

    Args:
        workspace: Public API transport.
        native: Pinned rename/webhook adapter.
        plan: Frozen source and destination mapping, created before writes.
        journal_path: Durable checkpoint; reruns preserve edits made after conversion.

    Returns:
        Migration checkpoint with verified dataset and case identities.
    """
    fingerprint = content_hash(canonical_json(plan))
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {
        'plan_sha256': fingerprint, 'items': [], 'datasets': []}
    if journal['plan_sha256'] != fingerprint:
        raise ValueError('Migration journal belongs to a different source export')
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    for dataset in plan['datasets']:
        identity = {'datasetId': dataset['id']}
        current = native.call('byId', identity, read=True)
        if current['name'] not in {dataset['old_name'], dataset['name']}:
            raise ValueError('Dataset renamed outside this migration')
        if current['name'] != dataset['name']:
            response = native.call('updateDataset', {**identity, 'name': dataset['name']})
            if response.get('success') is False:
                raise ValueError('Native rename validation failed')
        for item in dataset['items']:
            before, after = item['original'], item['converted']
            if before['id'] in journal['items']:
                continue
            live = workspace.request('GET', 'dataset-items/' + quote(before['id'], safe=''))
            desired = {'id': before['id'], 'datasetName': dataset['name'], 'input': after['input'],
                       'expectedOutput': after['expected_output'], 'metadata': after['metadata'], 'status': after['status']}
            # A write can have succeeded immediately before a process crash.
            keys = ('input', 'expectedOutput', 'metadata', 'status')
            already_written = all(live.get(key) == desired.get(key) for key in keys)
            if not already_written:
                if any(live.get(key) != before.get(key) for key in keys):
                    raise ValueError(f"Concurrent UI edit on item {before['id']}; export and review before retry")
                desired.update({key: before[key] for key in ('sourceTraceId', 'sourceObservationId') if before.get(key)})
                workspace.request('POST', 'dataset-items', json=desired)
            verified = workspace.request('GET', 'dataset-items/' + quote(before['id'], safe=''))
            if verified['datasetId'] != dataset['id'] or any(verified.get(key) != desired.get(key) for key in keys):
                raise ValueError('Converted item failed round-trip verification')
            journal['items'].append(before['id'])
            atomic_write(journal_path, canonical_json(journal))
        if dataset['id'] in journal['datasets']:
            continue
        actual = native.items(dataset['id'])
        if {i['id'] for i in actual} != {i['original']['id'] for i in dataset['items']}:
            raise ValueError('Dataset membership changed during migration; review new live cases')
        workspace.request('POST', 'v2/datasets', json={
            'name': dataset['name'], 'description': current.get('description'),
            'metadata': {**(current.get('metadata') or {}), 'suite': dataset['suite'], 'contract_version': 2},
            'inputSchema': dataset['schemas']['input'], 'expectedOutputSchema': dataset['schemas']['expected_output']})
        trigger = native.call('getRemoteExperiment', identity, read=True)
        if trigger and dataset['suite']['name'] != AssistantName.ANALYZE_TRANSCRIPT:
            from .models import RunConfig
            try:
                old_default = json.loads(trigger.get('defaultPayload') or '{}')
            except ValueError:
                old_default = None
            if old_default == RunConfig().model_dump():
                native.call('upsertRemoteExperiment', {**identity, 'url': trigger['url'],
                    'enabled': trigger.get('enabled', True),
                    'defaultPayload': json.dumps({'variants': [{'name': 'baseline'}]})})
        if dataset['suite']['name'] == AssistantName.ANALYZE_TRANSCRIPT:
            trigger = native.call('getRemoteExperiment', identity, read=True)
            if trigger:
                native.call('deleteRemoteExperiment', identity)
        journal['datasets'].append(dataset['id'])
        atomic_write(journal_path, canonical_json(journal))
    journal['complete'] = True
    atomic_write(journal_path, canonical_json(journal))
    return journal
