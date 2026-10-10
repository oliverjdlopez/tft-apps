"""Verify native Playground translation, isolation, streaming, and failures."""
import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from evals.langfuse.models import PlaygroundRequest
from evals.langfuse.playground import configure_connection
from evals.langfuse.server import create_app
from evals.langfuse.utils import playground_payload
from domain.assistants.constants import AssistantName


def request_body(**overrides):
    """Build a representative request from the native prompt Playground."""
    return {"model": f"chattft/{AssistantName.UNIT_EXPERT}", "messages": [
        {"role": "system", "content": "Draft instructions"},
        {"role": "user", "content": "Compare two units"}], **overrides}


def test_translation_keeps_draft_out_of_conversation():
    """Edits override exactly one base prompt while preserving prior dialogue."""
    body = request_body(temperature=0.2, max_completion_tokens=800)
    body['messages'].insert(1, {'role': 'assistant', 'content': 'Earlier answer'})
    payload = playground_payload(PlaygroundRequest(**body))
    assert payload['config']['prompt_candidates'] == {
        AssistantName.UNIT_EXPERT: {'text': 'Draft instructions', 'native_reference': None}}
    assert payload['input']['messages'] == body['messages'][1:]
    assert payload['config']['model_settings'] == {'temperature': 0.2, 'max_tokens': 800}
    assert 'database' not in payload['config']
    assert 'model' not in payload['config']
    fresh = playground_payload(PlaygroundRequest(**request_body(messages=[{'role': 'user', 'content': 'Hello'}])))
    assert fresh['config']['prompt_candidates'] == {}


@pytest.mark.parametrize('override', [
    {'model': 'gpt-4.1'}, {'tools': [{'type': 'function'}]}, {'n': 2},
    {'messages': [{'role': 'system', 'content': 'No user'}]},
    {'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {}}]}]},
    {'response_format': {'type': 'json_object'}},
])
def test_invalid_input_does_not_execute(override, monkeypatch):
    """Unsupported settings fail explicitly before database or model access."""
    operation = Mock()
    monkeypatch.setattr('evals.utils.isolated_operation', operation)
    with TestClient(create_app(service=Mock(), token='secret')) as http:
        result = http.post('/v1/chat/completions', json=request_body(**override),
                           headers={'Authorization': 'Bearer secret'})
        assert result.status_code == 400
        assert result.json()['error']['message']
    operation.assert_not_called()


@pytest.mark.parametrize('stream', [False, True])
def test_backend_completion_and_trace_link(stream, monkeypatch):
    """Both transports run one isolated graph and expose inspection and usage."""
    operation = Mock(return_value={'output': 'Real graph answer', 'metadata': {'database': 'test_db'},
                                  'token_usage': {'prompt': 10, 'completion': 5, 'total': 15}})
    monkeypatch.setattr('evals.utils.isolated_operation', operation)
    service = Mock()
    observation = Mock(trace_id='abc', id='root-span')
    service.client.start_as_current_observation.return_value.__enter__ = Mock(return_value=observation)
    service.client.start_as_current_observation.return_value.__exit__ = Mock(return_value=False)
    service.client.get_trace_url.return_value = 'http://localhost:15510/project/tft-apps-evals/traces/abc'
    with TestClient(create_app(service=service, token='secret')) as http:
        assert http.get('/v1/models').status_code == 401
        result = http.post('/v1/chat/completions', json=request_body(stream=stream, stream_options={'include_usage': True}),
                           headers={'Authorization': 'Bearer secret'})
        assert result.status_code == 200
        assert 'Real graph answer' in result.text
        assert '/traces/abc?observation=root-span' in result.text
        if stream:
            frames = [json.loads(line[6:]) for line in result.text.splitlines() if line.startswith('data: {')]
            assert frames[-1]['usage']['total_tokens'] == 15
            assert frames[-2]['choices'][0]['finish_reason'] == 'stop'
            assert result.text.endswith('data: [DONE]\n\n')
        else:
            assert result.json()['usage']['total_tokens'] == 15
    operation.assert_called_once()
    assert operation.call_args.kwargs['timeout'] == 180
    observation.update.assert_called_once_with(output='Real graph answer', metadata={'database': 'test_db'})


def test_connection_is_separate_from_judge():
    """Installing the adapter only updates its explicitly owned provider."""
    workspace = Mock()
    configure_connection(workspace, 'private')
    body = workspace.request.call_args.kwargs['json']
    assert body['provider'] == 'ChatTFT backend'
    assert body['baseURL'] == 'http://experiments/v1'
    assert body['withDefaultModels'] is False
    assert f"chattft/{AssistantName.UNIT_EXPERT}" in body['customModels']
    assert body['customModels'][0] == 'chattft/chat'
    assert 'chattft/AGENTS' not in body['customModels']


@pytest.mark.parametrize('stream', [False, True])
def test_worker_failure_is_inspectable_and_releases_capacity(stream, monkeypatch):
    """Failed executions return an error and trace link without exposing secrets."""
    monkeypatch.setattr('evals.utils.isolated_operation', Mock(return_value={'error': 'provider secret=do-not-leak'}))
    service = Mock()
    observation = Mock(trace_id='failed')
    service.client.start_as_current_observation.return_value.__enter__ = Mock(return_value=observation)
    service.client.start_as_current_observation.return_value.__exit__ = Mock(return_value=False)
    service.client.get_trace_url.return_value = 'http://localhost:15510/failed-trace'
    with TestClient(create_app(service=service, token='secret')) as http:
        for _ in range(5):
            response = http.post('/v1/chat/completions', json=request_body(stream=stream),
                                 headers={'Authorization': 'Bearer secret'})
            assert response.status_code == (200 if stream else 502)
            assert 'failed-trace' in response.text
            assert 'do-not-leak' not in response.text
            assert 'error' in response.text
    assert observation.update.call_args.kwargs['level'] == 'ERROR'


def test_capacity_rejected_without_starting_worker(monkeypatch):
    """A saturated adapter returns an explicit retryable response before spending."""
    gate = Mock()
    gate.acquire.return_value = False
    monkeypatch.setattr('evals.langfuse.playground.slots', gate)
    operation = Mock()
    monkeypatch.setattr('evals.utils.isolated_operation', operation)
    with TestClient(create_app(service=Mock(), token='secret')) as http:
        response = http.post('/v1/chat/completions', json=request_body(), headers={'Authorization': 'Bearer secret'})
        assert response.status_code == 429
    operation.assert_not_called()
    gate.release.assert_not_called()
