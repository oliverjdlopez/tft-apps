"""Natural contracts, lossless migration, and asynchronous acceptance regressions."""
from copy import deepcopy
from pathlib import Path

import pytest

from evals.execution import execute_attempt, score_attempt
from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle
from evals.langfuse.contracts import migrate_bundle, legacy_execution_item, validate_natural_item
from evals.langfuse.grading import reconcile_report
from evals.langfuse.jobs import JobStore
from domain.assistants.constants import AssistantName

ROOT = Path(__file__).parents[1] / 'snapshots'


def bundles():
    """Read the committed corpus without live services or model credentials."""
    result = [load_snapshot(entry['snapshot'], ROOT) for entry in load_catalog(ROOT)
              if entry.get('scoring') != 'none']
    for bundle in result:
        if bundle['schema_version'] in {2, 3}:
            bundle['schema_version'] = 1
            bundle['items'] = [deepcopy(item['metadata']['legacy_definition']) for item in bundle['items'] if item['metadata'].get('scoring') != 'none' and 'legacy_definition' in item['metadata']]
    return result


def test_every_assertion_and_threshold_survives_conversion():
    """Audit all retained rubrics and deterministic definitions independently."""
    profiles = {}
    for original in bundles():
        converted = migrate_bundle(original, available_skills={'tft-statistical-investigation'})
        validate_bundle(converted)
        assert migrate_bundle(converted) == converted
        for before, after in zip(original['items'], converted['items'], strict=True):
            assert after['metadata']['legacy_definition'] == before
            mappings = [row for row in converted['assertion_manifest'] if row['case_id'] == before['id']]
            assert [row['assertion'] for row in mappings] == before['expected_output']['assertions']
            for row in mappings:
                if 'evaluator' in row:
                    profiles[row['evaluator']] = profiles.get(row['evaluator'], 0) + 1
                    assert after['expected_output']['requirements'][row['requirement_index']] == row['assertion']['rubric']
    assert profiles == {'answer_quality': 9, 'scope_honesty': 1, 'rolldown_quality': 1,
                        'terminology_preservation': 1, 'signal_retention': 1}


def test_fixture_deterministic_parity_and_natural_output():
    """Keep Python regex, tool, and handoff checks equivalent across contracts."""
    before = next(bundle for bundle in bundles() if bundle['suite']['name'] == AssistantName.DUMMY_ASSISTANT)
    after = migrate_bundle(before)
    result = execute_attempt(after['suite'], after['items'][0], {}, after['prompts'])
    old_scores = score_attempt(before['items'][0], result, before['prompts'])
    new_scores = score_attempt(after['items'][0], result, after['prompts'])
    assert new_scores[:-2] == old_scores[:-2]
    assert [score['name'] for score in new_scores[-2:]] == ['execution_success', 'contract_pass']
    assert all(score['passed'] for score in new_scores)


def test_new_chat_case_requires_no_internal_assertions():
    """Accept replayable conversations and readable user-authored references."""
    suite = {'name': AssistantName.CHAT, 'family': 'assistant'}
    item = {'input': {'messages': [{'role': 'user', 'content': 'Compare these.'},
                                  {'role': 'assistant', 'content': 'Which units?'},
                                  {'role': 'user', 'content': 'Riven and Jax.'}]},
            'expected_output': 'Ask for missing scope; do not invent data.', 'metadata': {}}
    validate_natural_item(suite, item)
    assert legacy_execution_item(item)['input']['messages'] == item['input']['messages']
    item['input']['internal_scope_id'] = 'private'
    with pytest.raises(Exception):
        validate_natural_item(suite, item)


def test_unscored_chat_cases_require_only_native_inputs():
    """Keep prompt-intake execution free of references and grading configuration."""
    suite = {'name': 'chat_intake', 'assistant': AssistantName.CHAT, 'family': 'assistant',
             'scoring': 'none'}
    item = {'input': {'messages': [{'role': 'user', 'content': 'Explore this question.'}]},
            'expected_output': None, 'metadata': {}}
    validate_natural_item(suite, item)
    item['expected_output'] = {}
    with pytest.raises(ValueError, match='omit expected output'):
        validate_natural_item(suite, item)
    item['expected_output'] = None
    item['metadata']['quality_profile'] = 'answer_quality'
    with pytest.raises(ValueError, match='grading metadata'):
        validate_natural_item(suite, item)


class GradingAPI:
    """Model delayed native ingestion, evaluator edits, and score upserts."""

    def __init__(self):
        """Start with one unchanged evaluator and a visible experiment root."""
        self.definition = {'id': 'judge', 'version': 1, 'versionId': 'v1', 'status': 'active'}
        self.scores = []
        self.writes = {}
        self.root_visible = True

    def request(self, method, path, **kwargs):
        """Read the current definition or idempotently persist final scores."""
        if method == 'GET':
            return deepcopy(self.definition)
        body = kwargs['json']
        self.writes[body['id']] = body
        return body

    def list(self, path, **kwargs):
        """Return paginated API results already collected by the transport."""
        if path == 'experiment-items':
            return [{'id': 'root', 'traceId': 'trace', 'experimentItemId': 'item'}] if self.root_visible else []
        return deepcopy(self.scores)


def pending_report():
    """Construct a checkpoint after successful application execution."""
    return {'group_id': 'job', 'started_at': '2026-09-15T00:00:00Z', 'grading_deadline': 600,
            'experiments': [{'dataset_run_id': 'run', 'items': [
                {'remote_id': 'item', 'trace_id': 'trace', 'quality_profile': 'answer_quality',
                 'execution_success': True, 'contract_pass': True}]}]}


def frozen_grading(api):
    """Freeze the evaluator identity and native acceptance configuration."""
    return {'evaluators': {'answer_quality': deepcopy(api.definition)}, 'score_configs': {'attempt_pass': 'config'}}


def quality_score(value=.9):
    """Represent a native numeric judgment with explanatory evidence."""
    return {'id': 'score', 'dataType': 'NUMERIC', 'value': value, 'comment': 'Supported by the reference.',
            'metadata': {'evaluator_id': 'judge', 'evaluator_version_id': 'v1'}}


def test_missing_late_duplicate_scores_and_idempotent_completion():
    """Wait for actual native grades; duplicate transport rows cannot double-count."""
    api = GradingAPI()
    frozen = frozen_grading(api)
    pending = reconcile_report(api, pending_report(), frozen, now=100)
    assert pending['state'] == 'awaiting_scores' and not pending['passed'] and not api.writes
    api.scores = [quality_score(), quality_score()]
    result = reconcile_report(api, pending, frozen, now=599)
    assert result['passed']
    assert reconcile_report(api, result, frozen, now=599)['passed']
    assert len(api.writes) == 1
    api.scores.append({**quality_score(), 'id': 'another'})
    assert not reconcile_report(api, pending, frozen, now=599)['passed']


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -1, 1.1, True, '.9', .79])
def test_invalid_or_failing_native_results_never_pass(value):
    """Reject invalid provider outputs and below-threshold judgments."""
    api = GradingAPI()
    api.scores = [quality_score(value)]
    assert not reconcile_report(api, pending_report(), frozen_grading(api), now=100)['passed']


def test_deadline_and_evaluator_drift_fail_closed():
    """Do not treat execution completion or edited evaluators as passing grades."""
    api = GradingAPI()
    frozen = frozen_grading(api)
    expired = reconcile_report(api, pending_report(), frozen, now=600)
    assert expired['state'] == 'completed' and not expired['passed']
    assert 'deadline' in expired['experiments'][0]['items'][0]['grading_error']
    api.scores = [quality_score()]
    api.definition['version'] = 2
    changed = reconcile_report(api, pending_report(), frozen, now=100)
    assert not changed['passed'] and not changed['comparable']


def test_restart_recovers_scores_without_repeating_execution(tmp_path):
    """Keep awaiting jobs durable while interrupted executions require explicit replay."""
    store = JobStore(tmp_path)
    identity = store.submit({'grading': {}}, 'snapshot')
    store.claim()
    store.awaiting_scores(identity, pending_report())
    restarted = JobStore(tmp_path)
    assert restarted.recover() == []
    assert restarted.claim() is None
    assert restarted.pending_scores()[0]['result'] == pending_report()


def test_score_export_follows_v4_cursor_without_losing_history():
    """The v4 score endpoint returns meta.cursor, unlike evaluator nextCursor."""
    import httpx
    from evals.langfuse.workspace import Workspace
    requests = []

    def response(request):
        """Return a full first page and a final historical score on the next page."""
        requests.append(dict(request.url.params))
        if request.url.params.get('cursor') == 'older':
            return httpx.Response(200, json={'data': [{'id': 'historical'}], 'meta': {'cursor': None}})
        return httpx.Response(200, json={'data': [{'id': str(i)} for i in range(100)], 'meta': {'cursor': 'older'}})

    workspace = Workspace('http://test', 'public', 'secret')
    workspace.http.close()
    workspace.http = httpx.Client(base_url='http://test', transport=httpx.MockTransport(response))
    try:
        result = workspace.list('v3/scores', cursor=True)
        assert len(result) == 101
        assert result[-1]['id'] == 'historical'
        assert requests[1]['cursor'] == 'older'
    finally:
        workspace.close()


def test_missing_execution_result_fails_without_waiting_for_scores():
    """An omitted SDK result is an execution failure, not pending native grading."""
    api = GradingAPI()
    report = pending_report()
    del report['experiments'][0]['items'][0]['trace_id']
    grading = {'evaluators': {'answer_quality': api.definition}, 'score_configs': {'attempt_pass': 'pass'}}
    result = reconcile_report(api, report, grading, now=1)
    assert result['state'] == 'completed'
    assert not result['passed']
    assert result['experiments'][0]['items'][0]['grading_error'].startswith('Missing SDK')


def test_isolated_replay_requires_matching_restored_evaluators_and_rules(monkeypatch):
    """Different resource IDs are portable; different evaluator behavior is not."""
    from evals.langfuse import grading as module
    definition = {'id': 'source-judge', 'versionId': 'source-version', 'type': 'llm_as_judge',
                  'prompt': [{'role': 'user', 'content': '{{input}}'}], 'modelConfig': {'model': 'fixed'},
                  'variableMapping': [{'variable': 'input', 'source': 'input'}], 'outputDefinition': {'dataType': 'NUMERIC'}}
    rule = {'enabled': True, 'sampling': 1, 'filter': [{'column': 'datasetId', 'value': ['source-dataset']}],
            'evaluatorAssignments': [{'evaluatorId': 'source-judge', 'variableMapping': definition['variableMapping']}]}
    source = {'evaluators': {'answer_quality': definition}, 'rules': {'answer_quality': rule},
              'datasets': {'source-dataset': 'chattft/chat/end-to-end'}}
    destination = deepcopy(source)
    destination['evaluators']['answer_quality'].update(id='target-judge', versionId='target-version')
    destination['rules']['answer_quality']['filter'][0]['value'] = ['target-dataset']
    destination['rules']['answer_quality']['evaluatorAssignments'][0]['evaluatorId'] = 'target-judge'
    destination['datasets'] = {'target-dataset': 'chattft/chat/end-to-end'}
    monkeypatch.setattr(module, 'freeze_grading', lambda *_: deepcopy(destination))
    monkeypatch.setattr(module, 'verify_grading', lambda *_: None)
    assert module.rebind_grading(None, source, {}) == destination
    destination['evaluators']['answer_quality']['modelConfig']['model'] = 'changed'
    with pytest.raises(ValueError, match='Restore the frozen evaluator'):
        module.rebind_grading(None, source, {})
    destination['evaluators']['answer_quality']['modelConfig']['model'] = 'fixed'
    destination['rules']['answer_quality']['sampling'] = .5
    with pytest.raises(ValueError, match='Restore the frozen evaluation rule'):
        module.rebind_grading(None, source, {})


def test_quality_score_must_come_from_the_frozen_rule():
    """The correct evaluator alone cannot substitute for the required rule's grade."""
    api = GradingAPI()
    api.scores = [quality_score()]
    frozen = frozen_grading(api)
    frozen['rules'] = {'answer_quality': {'id': 'expected-rule'}}
    assert not reconcile_report(api, pending_report(), frozen, now=100)['passed']
    api.scores[0]['metadata']['evaluation_rule_id'] = 'expected-rule'
    assert reconcile_report(api, pending_report(), frozen, now=100)['passed']


def test_assistant_quality_cannot_be_disabled_with_null_metadata():
    """Specialized cases may change profile but cannot bypass quality acceptance."""
    item = {'input': {'messages': [{'role': 'user', 'content': 'Hello'}]},
            'expected_output': 'A greeting', 'metadata': {'quality_profile': None}}
    with pytest.raises(ValueError, match='require a native quality profile'):
        validate_natural_item({'name': AssistantName.CHAT, 'family': 'assistant'}, item)
