"""Credential-free OpenAI-compatible endpoint for native judge scheduling tests."""
from __future__ import annotations

import json
import time
from uuid import uuid4

from fastapi import FastAPI, Request

app = FastAPI()


def schema_value(schema: dict, *, failing: bool):
    """Produce a deterministic valid response to the platform's structured schema."""
    if schema.get('type') == 'object':
        return {name: schema_value(value, failing=failing) for name, value in schema.get('properties', {}).items()}
    if schema.get('type') in {'number', 'integer'}:
        return .2 if failing else .95
    if schema.get('type') == 'boolean':
        return not failing
    if schema.get('type') == 'array':
        return []
    return 'Mock evaluator: requirement violated.' if failing else 'Mock evaluator: all requirements satisfied.'


@app.get('/v1/models')
def models():
    """Expose a local model for the Langfuse connection validation workflow."""
    return {'object': 'list', 'data': [{'id': 'mock-judge', 'object': 'model', 'owned_by': 'test'}]}


@app.post('/v1/chat/completions')
async def completion(request: Request):
    """Exercise actual Langfuse scheduling while producing no paid model calls."""
    body = await request.json()
    failing = 'TEST_FAILURE' in json.dumps(body.get('messages', []))
    schema = body.get('response_format', {}).get('json_schema', {}).get('schema', {})
    content = json.dumps(schema_value(schema, failing=failing) if schema else
                         {'score': .2 if failing else .95, 'reasoning': 'Mock evaluator explanation.'})
    return {'id': 'chatcmpl-' + uuid4().hex, 'object': 'chat.completion', 'created': int(time.time()),
            'model': body['model'], 'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': content},
                                                'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}}


@app.post('/v1/responses')
async def response(request: Request):
    """Run real application SDK paths against deterministic local responses."""
    from fastapi.responses import StreamingResponse
    body = await request.json()
    timeout_case = 'TRACE_TIMEOUT_TEST' in json.dumps(body.get('input', []))
    if timeout_case and any(item.get('type') == 'function_call_output' for item in body.get('input', []) if isinstance(item, dict)):
        import asyncio
        await asyncio.sleep(20)
    schema = body.get('text', {}).get('format', {}).get('schema')
    text = json.dumps(schema_value(schema, failing=False)) if schema else 'Mock application reply.'
    message = {'id': 'msg_' + uuid4().hex, 'type': 'message', 'role': 'assistant', 'status': 'completed',
               'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}
    handoff = next((tool['name'] for tool in body.get('tools', []) if tool.get('name') == 'transfer_to_final_responder'), None)
    if timeout_case and handoff:
        message = {'id': 'fc_' + uuid4().hex, 'type': 'function_call', 'name': handoff,
                   'call_id': 'call_' + uuid4().hex, 'arguments': '{}', 'status': 'completed'}
    value = {'id': 'resp_' + uuid4().hex, 'object': 'response', 'created_at': int(time.time()),
             'status': 'completed', 'model': body['model'], 'output': [message],
             'parallel_tool_calls': True, 'tool_choice': 'auto', 'tools': [],
             'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
                       'input_tokens_details': {'cached_tokens': 0}, 'output_tokens_details': {'reasoning_tokens': 0}}}
    if not body.get('stream'):
        return value
    events = [
        {'type': 'response.created', 'response': {**value, 'status': 'in_progress', 'output': []}},
        {'type': 'response.output_item.added', 'output_index': 0, 'item': {**message, 'status': 'in_progress', 'content': []}},
        {'type': 'response.content_part.added', 'item_id': message['id'], 'output_index': 0, 'content_index': 0,
         'part': {'type': 'output_text', 'text': '', 'annotations': []}},
        {'type': 'response.output_text.delta', 'item_id': message['id'], 'output_index': 0, 'content_index': 0, 'delta': text},
        {'type': 'response.output_text.done', 'item_id': message['id'], 'output_index': 0, 'content_index': 0, 'text': text},
        {'type': 'response.output_item.done', 'output_index': 0, 'item': message},
        {'type': 'response.completed', 'response': value},
    ]
    frames = [f"event: {event['type']}\ndata: {json.dumps({**event, 'sequence_number': index})}\n\n"
              for index, event in enumerate(events)]
    return StreamingResponse(iter(frames), media_type='text/event-stream')
