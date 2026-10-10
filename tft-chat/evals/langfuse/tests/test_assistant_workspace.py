"""Captured definitions, exact comparisons, and duplicate submission acceptance."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from fastapi import Request

from domain.assistants.capture import capture, digest, from_capture, registry_from_files
from evals.langfuse import assistant_workspace as module
from evals.langfuse.jobs import JobStore
from evals.langfuse.content import validate_bundle
from evals.langfuse.tests.test_content import FakeClient


def graph(prompt='Active', handoffs=None):
    """Build an isolated, tool-free graph with optional frozen handoffs."""
    import json
    files = {'fixture': {'system.md': prompt, 'agent.json': json.dumps({'handoffs': handoffs or [], 'skills': []})},
             'target': {'system.md': 'Frozen target'}}
    return capture(registry_from_files(files))


def bundle(execution):
    """Use an unscored natural dataset to exercise preparation without services."""
    return {'schema_version': 3, 'dataset_id': 'dataset', 'dataset_name': 'registered', 'dataset_version': '2026-10-10T00:00:00+00:00',
            'suite': {'name': 'fixture', 'assistant': 'fixture', 'family': 'assistant', 'execution': 'live', 'scoring': 'none'},
            'items': [{'id': 'fixture/case', 'remote_id': 'case', 'input': 'Question', 'expected_output': None, 'metadata': {'case': 'case', 'scoring': 'none'}}],
            'prompts': {}, 'config': {'variants': [{'name': 'Active', 'model': None, 'prompts': {}}, {'name': 'Draft', 'model': None, 'prompts': {}}],
                                    'repetitions': 1, 'cases': [], 'concurrency': 4}, 'execution': execution}


def test_capture_preserves_models_handoffs_and_hash_independently_of_source():
    """Restored definitions never reread later source instructions or configuration."""
    frozen = graph(handoffs=['target'])
    registry = from_capture(frozen)
    assert registry.get_handoff_names('fixture') == ['target']
    assert registry.get_spec('target').system_prompt == 'Frozen target'
    assert registry.resolved_models['fixture'] == frozen['specs']['fixture']['resolved_model']
    broken = deepcopy(frozen)
    broken['specs']['fixture']['system_prompt'] = 'Intervening edit'
    with pytest.raises(ValueError, match='captured'):
        from_capture(broken)


def test_optional_execution_version_preserves_legacy_bundles():
    """Captured sections validate independently; snapshots without them stay readable."""
    frozen = graph()
    value = bundle({'version': 1, 'graphs': {'Active': frozen, 'Draft': frozen}})
    assert validate_bundle(value)['execution']['version'] == 1
    historical = deepcopy(value)
    historical.pop('execution')
    assert 'execution' not in validate_bundle(historical)
    value['execution']['version'] = 2
    with pytest.raises(ValueError, match='execution'):
        validate_bundle(value)


def test_managed_versions_never_fetch_authored_baseline():
    """Instruction copies carry complete specification identity and concrete versions."""
    client = FakeClient()
    client.prompts['chattft/assistants/fixture'] = SimpleNamespace(name='chattft/assistants/fixture', prompt='Stale baseline', version=9)
    frozen = graph()
    prompts = module.publish_graph_prompts(client, frozen)
    assert prompts['fixture']['text'] == 'Active'
    assert '/workspace/' in prompts['fixture']['name']
    assert prompts['fixture']['version'] == 1
    assert module.publish_graph_prompts(client, frozen) == prompts
    assert client.prompts['chattft/assistants/fixture'].prompt == 'Stale baseline'


def test_repeated_and_concurrent_submissions_schedule_once(tmp_path, monkeypatch):
    """The durable queue and submission receipt commit in the same transaction."""
    service = SimpleNamespace(runtime=tmp_path / 'runtime', snapshots=tmp_path / 'snapshots', jobs=JobStore(tmp_path / 'runtime'),
                              wakeup=threading.Event(), client=FakeClient(), provenance=lambda: {'git_revision': 'fixture'})
    service.snapshots.mkdir()
    monkeypatch.setattr(module, 'registered_datasets', lambda *args, **kwargs: [{'name': 'registered', 'assistant': 'fixture'}])
    calls = []
    def fetch(client, name, config, root, *, captured_execution):
        """Keep preparation observable without a live dataset or grading service."""
        calls.append(name)
        return bundle(captured_execution)
    monkeypatch.setattr(module, 'fetch_bundle', fetch)
    active, draft = graph(), graph('Draft')
    body = module.ComparisonRequest(submission_id='submission-test-1234', dataset='registered', active_graph=active, draft_graph=draft,
        lineage={'assistant': 'fixture', 'draft_revision': 'revision', 'active_graph_hash': active['hash'], 'draft_graph_hash': draft['hash']})
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        receipts = list(pool.map(lambda _: module.submit_comparison(service, body), range(3)))
    assert len({receipt['job_id'] for receipt in receipts}) == 1
    assert calls == ['registered']
    assert service.jobs.claim() is not None
    assert service.jobs.claim() is None
    restarted = JobStore(service.runtime)
    assert restarted.submission(body.submission_id)['job_id'] == receipts[0]['job_id']
    changed = body.model_copy(update={'repetitions': 2})
    with pytest.raises(ValueError, match='identifier'):
        module.submit_comparison(service, changed)


def test_failed_preparation_is_durable_and_does_not_schedule(tmp_path, monkeypatch):
    """Repeated clicks return the same failure instead of switching prompt sources."""
    service = SimpleNamespace(runtime=tmp_path, snapshots=tmp_path, jobs=JobStore(tmp_path), wakeup=threading.Event())
    monkeypatch.setattr(module, 'registered_datasets', lambda *args, **kwargs: [])
    frozen = graph()
    body = module.ComparisonRequest(submission_id='submission-failed-123', dataset='missing', active_graph=frozen, draft_graph=frozen, lineage={})
    first = module.submit_comparison(service, body)
    assert first['state'] == 'failed'
    assert first == module.submit_comparison(service, body)
    assert service.jobs.claim() is None


def test_attempt_passes_captured_variant_to_isolated_worker(monkeypatch):
    """Active and Draft use their own full graphs, never older hosted bases."""
    from evals import execution
    active, draft = graph(), graph('Draft', ['target'])
    suite = bundle({})['suite'] | {'captured_graphs': {'Active': active, 'Draft': draft}, 'workspace_lineage': {'draft_revision': 'exact'}}
    payloads = []
    def isolated(payload, timeout):
        """Capture the subprocess request without invoking a model."""
        payloads.append(payload)
        return {'output': 'answer', 'metadata': {}}
    monkeypatch.setattr(execution, 'isolated_operation', isolated)
    for name in ('Active', 'Draft'):
        execution.execute_attempt(suite, bundle({})['items'][0], {'name': name, 'prompts': {}}, {'fixture': {'text': 'Stale baseline'}})
    assert payloads[0]['config']['captured_graph'] == active
    assert payloads[1]['config']['captured_graph'] == draft
    assert all(not payload['config']['prompt_candidates'] for payload in payloads)


def test_real_subprocess_executes_captured_handoffs_tools_models_and_wrappers(monkeypatch):
    """Run the actual SDK against a local model with an isolated _test target."""
    import json
    import socket
    import time
    import uuid
    from fastapi import FastAPI, Request
    import uvicorn
    from evals.utils import isolated_operation
    requests = []
    app = FastAPI()

    @app.post('/v1/responses')
    async def response(request: Request):
        """Return handoff/tool calls before one deterministic model answer."""
        body = await request.json()
        requests.append(body)
        if 'FAIL_MODEL' in str(body.get('input')):
            from fastapi.responses import JSONResponse
            return JSONResponse({'error': {'message': 'Mock failure', 'type': 'invalid_request_error', 'param': None, 'code': None}}, status_code=400)
        schema = body.get('text', {}).get('format', {}).get('schema')
        tools = {tool['name'] for tool in body.get('tools', []) if 'name' in tool}
        if schema:
            content = '{"selections":[]}' if 'selections' in schema.get('properties', {}) else '{"selected_ids":[]}'
            call = None
        elif 'transfer_to_target' in tools:
            call, arguments = 'transfer_to_target', '{}'
        elif 'request_additional_context' in tools and not any(item.get('name') == 'request_additional_context' for item in body.get('input', []) if isinstance(item, dict)):
            call, arguments = 'request_additional_context', '{"request":{"query":"Wisp rules"}}'
        else:
            call, content = None, 'Mock application reply.'
        output = ({'id': 'fc_' + uuid.uuid4().hex, 'type': 'function_call', 'name': call,
                   'call_id': 'call_' + uuid.uuid4().hex, 'arguments': arguments, 'status': 'completed'} if call else
                  {'id': 'msg_' + uuid.uuid4().hex, 'type': 'message', 'role': 'assistant', 'status': 'completed',
                   'content': [{'type': 'output_text', 'text': content, 'annotations': []}]})
        return {'id': 'resp_' + uuid.uuid4().hex, 'object': 'response', 'created_at': int(time.time()),
                'status': 'completed', 'model': body['model'], 'output': [output], 'parallel_tool_calls': True,
                'tool_choice': 'auto', 'tools': [], 'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
                'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    for key, value in {'OPENAI_API_KEY': 'mock-key', 'OPENAI_BASE_URL': f'http://127.0.0.1:{port}/v1',
        'RDS_EVAL_HOST': '127.0.0.1', 'RDS_EVAL_PORT': '5432', 'RDS_EVAL_ADMIN': 'mock',
        'RDS_EVAL_DB': 'assistant_workspace_test', 'RDS_EVAL_PASSWORD': 'mock-password', 'RDS_EVAL_SYNC_LOCAL_IP': 'false'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv('LANGFUSE_PUBLIC_KEY', raising=False)
    monkeypatch.delenv('LANGFUSE_SECRET_KEY', raising=False)
    files = {'fixture': {'system.md': 'Captured draft root', 'task.md': 'Frozen task wrapper',
                        'agent.json': json.dumps({'model': 'gpt-6-sol', 'reasoning': 'low', 'skills': [], 'handoffs': ['target']})},
             'target': {'system.md': 'Captured handoff policy', 'agent.json': '{"model":"gpt-6-luna","tools":{"groups":["context"]},"skills":[]}'},
             'context_selector': {'system.md': 'Select no context', 'agent.json': '{"model":"gpt-6-luna","skills":[]}'},
             'skill_selector': {'system.md': 'Select no skills', 'agent.json': '{"model":"gpt-6-luna","skills":[]}'}}
    frozen = capture(registry_from_files(files))
    try:
        result = isolated_operation({'operation': 'evaluate', 'config': {'family': 'assistant', 'assistant': 'fixture',
            'captured_graph': frozen, 'workspace_trial': True, 'max_turns': 10}, 'input': {'input': 'Question'}}, 30)
        assert not result.get('error'), result
        assert result['output'] == 'Mock application reply.'
        metadata = result['metadata']
        assert metadata['database'] == 'assistant_workspace_test'
        assert metadata['assembled_instructions']['fixture'] == 'Captured draft root'
        assert metadata['assembled_instructions']['target'] == 'Captured handoff policy'
        assert any(row['name'] == 'request_additional_context' for row in metadata['tft_trace']['tool_calls'])
        assert metadata['tft_trace']['handoffs'][0]['target'] == 'target'
        root = next(row for row in requests if row.get('instructions') == 'Captured draft root')
        assert root['model'] == 'gpt-6-sol'
        assert root['reasoning']['effort'] == 'low'
        assert 'Frozen task wrapper' in str(root['input'])
        assert result['token_usage']['numRequests'] >= 3
        assert metadata['model_settings']['fixture']['model'] == 'gpt-6-sol'
        failed = isolated_operation({'operation': 'evaluate', 'config': {'family': 'assistant', 'assistant': 'fixture',
            'captured_graph': frozen, 'workspace_trial': True, 'max_turns': 10}, 'input': {'input': 'FAIL_MODEL'}}, 30)
        assert failed['error']
        assert failed['metadata']['assembled_instructions']['fixture'] == 'Captured draft root'
        assert failed['metadata']['execution_provenance']['git_revision']
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()


@pytest.mark.parametrize('existing,updates', [
    (None, 1),
    ({'url': 'http://experiments/experiments', 'defaultPayload': '{"variants":[{"name":"baseline"}]}', 'enabled': False, 'requestHeaders': {'Custom': {'value': 'keep'}}}, 1),
    ({'url': 'http://experiments/experiments', 'defaultPayload': '{"variants":[{"name":"authored"}]}', 'enabled': True}, 0),
    ({'url': 'http://other-service/experiments', 'defaultPayload': '{"variants":[{"name":"baseline"}]}'}, 0),
])
def test_webhook_default_migration_preserves_authored_settings(monkeypatch, tmp_path, existing, updates):
    """Only exact owned defaults migrate; user JSON, endpoints, and headers survive."""
    import json
    from evals.langfuse import seed, content
    writes = []
    class Native:
        """Model pinned remote-experiment reads without accessing a platform."""
        def __init__(self, *args):
            """Accept the bootstrap connection without using credentials."""
        def call(self, name, value, **kwargs):
            """Read authored settings or record one owned-default update."""
            if name == 'getRemoteExperiment':
                return existing
            writes.append(value)
        def close(self):
            """Release the no-op fixture transport."""
    monkeypatch.setattr(seed, 'NativeWorkspace', Native)
    monkeypatch.setattr(content, 'load_catalog', lambda root: [{'name': 'chat', 'execution': 'live'}])
    client = SimpleNamespace(get_dataset=lambda name: SimpleNamespace(id='dataset'))
    count = seed.configure_triggers(client, tmp_path, base_url='http://fixture', email='fixture', password='fixture', token='fixture')
    assert count == updates
    if updates:
        assert json.loads(writes[0]['defaultPayload']) == {'variants': [{'name': 'Active'}]}
        if existing:
            assert writes[0]['enabled'] is False
            assert writes[0]['requestHeaders'] == existing['requestHeaders']
