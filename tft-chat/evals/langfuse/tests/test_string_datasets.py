"""Verify string-only authoring, legacy replay, and lossless dataset consolidation."""
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from jsonschema import ValidationError

from evals.langfuse.consolidation import plan_consolidation, apply_consolidation
from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle
from evals.langfuse.contracts import dataset_schemas, legacy_execution_item, validate_natural_item
from evals.langfuse.experiments import evaluate_item, run_item_task

ROOT = Path(__file__).parents[1] / 'snapshots'


def test_string_containing_input_is_never_mistaken_for_legacy_object():
    """Treat ordinary words and JSON-looking text as literal user content."""
    for text in ['input', '{"input": "hello"}', 'Compare two units.']:
        item = {'input': text, 'expected_output': 'Ground the answer.', 'metadata': {}}
        validate_natural_item({'name': 'chat', 'family': 'assistant'}, item, version=3)
        assert legacy_execution_item(item)['input']['input'] == text


@pytest.mark.parametrize('value', [{'text': 'hello'}, {'messages': [{'role': 'user', 'content': 'hello'}]},
                                  {'input': 'hello'}, ['hello'], 42, None])
def test_string_schema_rejects_every_nonstring(value):
    """New hosted contracts cannot silently accept old object-shaped inputs."""
    with pytest.raises(ValidationError):
        validate_natural_item({'name': 'chat', 'family': 'assistant'},
                              {'input': value, 'expected_output': '', 'metadata': {}}, version=3)


def test_unscored_case_requires_explicit_metadata():
    """Missing reference data cannot silently disable grading for a scored case."""
    suite = {'name': 'chat', 'family': 'assistant'}
    item = {'input': 'hello', 'expected_output': None, 'metadata': {}}
    with pytest.raises(ValueError, match='require expected output'):
        validate_natural_item(suite, item, version=3)
    item['metadata']['scoring'] = 'none'
    validate_natural_item(suite, item, version=3)
    assert evaluate_item(input='hello', output={}, expected_output=None,
                         metadata=item['metadata'], prompts={}) == []


def test_deterministic_only_case_accepts_hosted_null_reference():
    """Langfuse may store an empty seed reference as null without disabling checks."""
    source = ROOT.parent.parent / 'datasets/context_response_smoke.json'
    bundle = json.loads(source.read_text())
    for item in bundle['items']:
        item['expected_output'] = None
    validate_bundle(bundle)
    item = bundle['items'][0]
    assert evaluate_item(input=item['input'], output={'output': item['input'], 'success': True},
                         expected_output=None, metadata=item['metadata'], prompts={})


def test_missing_reference_still_rejects_cases_without_deterministic_scoring():
    """A null reference cannot silently turn an ordinary scored case into intake."""
    suite = {'name': 'context_response_smoke', 'family': 'assistant'}
    item = {'input': 'hello', 'expected_output': None,
            'metadata': {'quality_profile': None, 'deterministic_checks': []}}
    with pytest.raises(ValueError, match='require expected output'):
        validate_natural_item(suite, item, version=3)
    item['metadata']['deterministic_checks'] = [
        {'name': 'topic', 'kind': 'trace', 'check': {'type': 'regex', 'value': 'hello'}}]
    with pytest.raises(ValueError, match='require expected output'):
        validate_natural_item({'name': 'chat', 'family': 'assistant'}, item, version=3)


def test_unscored_trace_does_not_schedule_quality_grading(monkeypatch):
    """An intake item inside the scored chat suite never inherits its judge."""
    monkeypatch.setattr('evals.langfuse.experiments.execute_attempt', lambda *args: {'output': 'ok'})
    client = Mock()
    run_item_task(item={'input': 'input question', 'expected_output': None,
                       'metadata': {'scoring': 'none'}},
                  suite={'name': 'chat', 'execution': 'live'}, variant={}, prompts={}, client=client)
    assert client.update_current_span.call_args.kwargs['metadata']['quality_profile'] == 'none'


def consolidation_fixture():
    """Build source-shaped cases using repository execution and prompt definitions."""
    baselines = {entry['name']: load_snapshot(entry['snapshot'], ROOT)
                 for entry in load_catalog(ROOT) if entry['name'] in {'chat', 'data_analyst'}}
    datasets = []
    for index, name in enumerate(['chattft/chat/end-to-end', 'chattft/chat/data-analysis',
                                  'chattft/intake/unscored-prompts', 'set18-buildout', 'unrelated']):
        datasets.append({'id': str(index), 'name': name, 'items': [{
            'id': f'item-{index}', 'input': {'messages': [{'role': 'user', 'content': 'input question'}]},
            'expectedOutput': None if index == 2 else '', 'metadata': {}, 'status': 'ACTIVE'}]})
    return {'datasets': datasets}, baselines


def test_consolidation_preserves_all_cases_and_deletes_only_requested_names():
    """Copy intake cases into chat without inventing expectations or losing lineage."""
    backup, baselines = consolidation_fixture()
    before = deepcopy(backup)
    plan = plan_consolidation(backup, baselines, delete_sources=True)
    assert backup == before
    assert {d['name'] for d in plan['deletions']} == {d['name'] for d in backup['datasets'][:-1]}
    assert len(plan['bundles']['end-to-end']['items']) == 2
    for bundle in plan['bundles'].values():
        validate_bundle(bundle)
        assert bundle['schemas']['input'] == {'type': 'string'}
        assert all(isinstance(item['input'], str) for item in bundle['items'])
    intake = plan['bundles']['end-to-end']['items'][1]
    assert intake['metadata']['scoring'] == 'none'
    assert intake['expected_output'] is None


def test_consolidation_rejects_multiturn_history():
    """Never flatten role boundaries merely to satisfy the new schema."""
    backup, baselines = consolidation_fixture()
    backup['datasets'][0]['items'][0]['input']['messages'].append({'role': 'assistant', 'content': 'reply'})
    with pytest.raises(ValueError, match='conversation history'):
        plan_consolidation(backup, baselines)


def test_concurrent_source_edit_prevents_all_writes(tmp_path):
    """Refuse the migration before copying or deleting changed source content."""
    backup, baselines = consolidation_fixture()
    plan = plan_consolidation(backup, baselines)
    workspace, native = Mock(), Mock()
    native.items.return_value = []
    with pytest.raises(ValueError, match='changed after backup'):
        apply_consolidation(workspace, native, plan, tmp_path / 'journal.json')
    workspace.request.assert_not_called()
    native.call.assert_not_called()


def test_failed_copy_never_deletes_source_datasets(tmp_path):
    """Source deletion is unreachable until destination content is verified."""
    backup, baselines = consolidation_fixture()
    plan = plan_consolidation(backup, baselines, delete_sources=True)
    workspace, native = Mock(), Mock()
    originals = {d['id']: d['items'] for d in backup['datasets']}
    native.items.side_effect = lambda identity: originals[identity]
    workspace.list.return_value = []
    workspace.request.side_effect = [{'id': 'new-chat'}, {}, {'datasetId': 'wrong'}]
    with pytest.raises(ValueError, match='round-trip'):
        apply_consolidation(workspace, native, plan, tmp_path / 'journal.json')
    native.call.assert_not_called()


@pytest.mark.parametrize('execution_success', [True, False])
def test_intake_completion_uses_execution_without_publishing_scores(execution_success):
    """Mixed experiments include intake failures without inventing quality scores."""
    from evals.langfuse.grading import reconcile_report

    workspace = Mock()
    workspace.list.return_value = [{'traceId': 'trace', 'experimentItemId': 'item', 'id': 'root'}]
    report = {'group_id': 'group', 'started_at': '2026-09-16T00:00:00Z', 'grading_deadline': 100,
              'experiments': [{'dataset_run_id': 'run', 'items': [{
                  'remote_id': 'item', 'trace_id': 'trace', 'quality_profile': None, 'scoring': 'none',
                  'execution_success': execution_success, 'contract_pass': True}]}]}
    result = reconcile_report(workspace, report, {'evaluators': {}, 'rules': {}}, now=1)
    assert result['state'] == 'completed'
    assert result['passed'] is execution_success
    workspace.request.assert_not_called()


def test_resume_rejects_changed_destination_before_writing(tmp_path):
    """A retry cannot overwrite an intervening edit to a copied destination case."""
    backup, baselines = consolidation_fixture()
    plan = plan_consolidation(backup, baselines)
    workspace, native = Mock(), Mock()
    first = next(iter(plan['bundles']))
    item = plan['bundles'][first]['items'][0]
    originals = {d['id']: d['items'] for d in backup['datasets']}
    native.items.side_effect = lambda identity: ([{'id': item['remote_id'], 'input': 'edited'}]
                                                if identity == 'destination' else originals[identity])
    workspace.list.return_value = [{'name': first, 'id': 'destination'}]
    with pytest.raises(ValueError, match='Destination case changed'):
        apply_consolidation(workspace, native, plan, tmp_path / 'journal.json')
    workspace.request.assert_not_called()
    native.call.assert_not_called()
