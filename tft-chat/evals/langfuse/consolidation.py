"""Plan and apply the root dataset consolidation from a private workspace backup."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from domain.assistants.constants import AssistantName

from .contracts import dataset_schemas, validate_natural_item
from .utils import atomic_write, canonical_json, content_hash


def plan_consolidation(backup: dict, baselines: dict, *, delete_sources: bool = False,
                       grade_intake: bool = False) -> dict:
    """Prepare exact copies and deletions without mutating the hosted workspace.

    Args:
        backup: Complete workspace export, including archived cases.
        baselines: Frozen chat and analyst definitions used for execution routing.
        delete_sources: Remove the three source datasets after verifying copies.
        grade_intake: Apply answer-quality grading to imported intake cases.

    Returns:
        A serializable plan retaining source identities and complete new bundles.
    """
    sources = {'chattft/chat/end-to-end': (AssistantName.CHAT, 'end-to-end'),
               'chattft/chat/data-analysis': (AssistantName.DATA_ANALYST, 'data-analysis'),
               'chattft/intake/unscored-prompts': (AssistantName.CHAT, 'end-to-end')}
    datasets = {dataset['name']: dataset for dataset in backup['datasets']}
    if set(sources) - datasets.keys():
        raise ValueError('Consolidation requires all three source datasets')
    if {'end-to-end', 'data-analysis'} & datasets.keys():
        raise ValueError('Root datasets already exist; resume the saved plan instead')
    bundles = {}
    for alias, name in [(AssistantName.CHAT, 'end-to-end'), (AssistantName.DATA_ANALYST, 'data-analysis')]:
        bundle = deepcopy(baselines[alias])
        for key in ('dataset_id', 'dataset_version', 'grading', 'snapshot_id'):
            bundle.pop(key, None)
        bundle.update(schema_version=3, dataset_name=name, items=[],
                      schemas=dataset_schemas(bundle['suite'], version=3))
        bundles[name] = bundle
    for source_name, (alias, target) in sources.items():
        for original in datasets[source_name]['items']:
            value = original['input']
            if isinstance(value, dict) and set(value) == {'messages'}:
                messages = value['messages']
                if len(messages) != 1 or messages[0]['role'] != 'user':
                    raise ValueError('Cannot collapse conversation history into a single user string')
                value = messages[0]['content']
            if not isinstance(value, str):
                raise ValueError('Source case cannot be converted losslessly to a string')
            metadata = deepcopy(original.get('metadata') or {})
            case = metadata.get('case') or original['id']
            if source_name.endswith('unscored-prompts'):
                case = 'intake-' + case
                if grade_intake:
                    metadata.update(quality_profile='answer_quality', quality_threshold=.8)
                else:
                    metadata['scoring'] = 'none'
            metadata.update(case=case, case_id=f'{alias}/{case}', suite=alias, contract_version=3,
                            source_dataset=source_name, source_item_id=original['id'])
            expected = deepcopy(original.get('expectedOutput'))
            if source_name.endswith('unscored-prompts') and grade_intake and expected is None:
                expected = {'requirements': []}
            item = {'id': metadata['case_id'],
                    'remote_id': content_hash(f"{target}:{original['id']}".encode()),
                    'input': value, 'expected_output': expected, 'metadata': metadata,
                    'status': original['status'],
                    'source_trace_id': original.get('sourceTraceId'),
                    'source_observation_id': original.get('sourceObservationId')}
            validate_natural_item(bundles[target]['suite'], item, version=3)
            bundles[target]['items'].append(item)
    removals = [dataset for name, dataset in datasets.items()
                if name.startswith(('internal/', 'archive/')) or name == 'set18-buildout'
                or name.startswith('chattft/') and (delete_sources or name not in sources)]
    return {'backup_sha256': content_hash(canonical_json(backup)), 'bundles': bundles,
            'sources': [datasets[name] for name in sources], 'deletions': removals}


def apply_consolidation(workspace, native, plan: dict, journal_path: Path) -> dict:
    """Copy and verify all cases before deleting only the backed-up datasets.

    Args:
        workspace: Authenticated public API transport.
        native: Pinned native dataset maintenance API.
        plan: Reviewed plan built from a complete private backup.
        journal_path: Durable record of successful destination copies and deletions.

    Returns:
        Verified destination identities and completed deletion IDs.
    """
    from urllib.parse import quote

    journal = {'datasets': {}, 'deleted': []}
    for source in {d['id']: d for d in [*plan['sources'], *plan['deletions']]}.values():
        if canonical_json(native.items(source['id'])) != canonical_json(source['items']):
            raise ValueError('Source dataset changed after backup; export and review again')
    current_datasets = {dataset['name']: dataset for dataset in workspace.list('v2/datasets')}
    for name, bundle in plan['bundles'].items():
        existing = current_datasets.get(name)
        existing_items = {item['id']: item for item in native.items(existing['id'])} if existing else {}
        planned = {item['remote_id']: item for item in bundle['items']}
        if set(existing_items) - set(planned):
            raise ValueError('Destination contains unplanned cases; refusing to overwrite it')
        for identity, actual in existing_items.items():
            expected = planned[identity]
            if any(actual.get(remote) != expected.get(local) for remote, local in (
                    ('input', 'input'), ('expectedOutput', 'expected_output'), ('metadata', 'metadata'),
                    ('status', 'status'), ('sourceTraceId', 'source_trace_id'),
                    ('sourceObservationId', 'source_observation_id'))):
                raise ValueError('Destination case changed; refusing to overwrite it')
        dataset = workspace.request('POST', 'v2/datasets', json={
            'name': name, 'description': bundle['suite']['description'],
            'metadata': {'suite': bundle['suite'], 'contract_version': 3, 'seed_complete': True},
            'inputSchema': bundle['schemas']['input'],
            'expectedOutputSchema': bundle['schemas']['expected_output']})
        for item in bundle['items']:
            if item['remote_id'] in existing_items:
                continue
            body = {'id': item['remote_id'], 'datasetName': name, 'input': item['input'],
                    'expectedOutput': item['expected_output'], 'metadata': item['metadata'],
                    'status': item['status']}
            body.update({remote: item[local] for remote, local in (
                ('sourceTraceId', 'source_trace_id'), ('sourceObservationId', 'source_observation_id'))
                if item.get(local)})
            workspace.request('POST', 'dataset-items', json=body)
            actual = workspace.request('GET', 'dataset-items/' + quote(item['remote_id'], safe=''))
            if actual['datasetId'] != dataset['id'] or any(
                    actual.get(key) != body.get(key) for key in body if key != 'datasetName'):
                raise ValueError('Destination case failed round-trip verification')
        if {item['id'] for item in native.items(dataset['id'])} != {item['remote_id'] for item in bundle['items']}:
            raise ValueError('Destination dataset membership differs from the planned copy')
        journal['datasets'][name] = dataset['id']
        atomic_write(journal_path, canonical_json(journal))
    # Native evaluator filters use dataset IDs, so copying cases alone would
    # leave the new experiments waiting for scores that can never arrive.
    replacements = {source['id']: journal['datasets'][
        'data-analysis' if source['name'].endswith('data-analysis') else 'end-to-end']
        for source in plan['sources']}
    removed = {source['id'] for source in plan['deletions']}
    for rule in workspace.list('v2/evaluation-rules', cursor=True):
        filters = deepcopy(rule['filter'])
        for condition in filters:
            if condition['column'] == 'datasetId':
                condition['value'] = sorted({replacements.get(identity, identity)
                    for identity in condition['value'] if identity in replacements or identity not in removed})
        if filters != rule['filter']:
            workspace.request('PATCH', 'v2/evaluation-rules/' + rule['id'], json={'filter': filters})
    for source in plan['deletions']:
        # Recheck immediately before deletion so UI edits are never discarded.
        if canonical_json(native.items(source['id'])) != canonical_json(source['items']):
            raise ValueError('Dataset changed during copying; deletion stopped')
        native.call('deleteDataset', {'datasetId': source['id']})
        journal['deleted'].append(source['id'])
        atomic_write(journal_path, canonical_json(journal))
    return journal
