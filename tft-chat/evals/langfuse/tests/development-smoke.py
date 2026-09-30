"""Exercise opt-in development chat with real SDK streaming against the CI model."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import time

from agents import OpenAIResponsesModel
from openai import AsyncOpenAI

from common.langfuse_tracing import initialize_tracing
from services import chat_service
from evals.langfuse.utils import atomic_write, canonical_json, configured_workspace


async def main():
    """Export a real development conversation for native browser regression capture."""
    if os.environ.get('LANGFUSE_TEST_DEPLOYMENT') != '1' or 'mock-model:8000' not in os.environ.get('OPENAI_BASE_URL', ''):
        raise RuntimeError('Development acceptance requires the isolated local mock deployment')
    config = chat_service.load_config()
    from agents import set_trace_processors
    from domain.assistants.token_logging import prompt_token_logger
    set_trace_processors([])
    prompt_token_logger.disabled = True
    # Exercise the same typed opt-in that the INI loader supplies in development.
    chat_service.load_config = lambda: replace(config, chat=replace(config.chat, langfuse_tracing=True))
    model = OpenAIResponsesModel('mock-judge', AsyncOpenAI(api_key='mock-key', base_url=os.environ['OPENAI_BASE_URL']))
    messages = [{'role': 'user', 'content': 'Hello!'}, {'role': 'assistant', 'content': 'Hello.'},
                {'role': 'user', 'content': 'Thanks! Please say hello again.'}]
    started = datetime.now(timezone.utc).isoformat()
    chunks = [chunk async for chunk in chat_service.stream_chat(messages, None, 'mock-judge', model=model, max_tool_rounds=3)]
    assert any('Mock application reply.' in chunk for chunk in chunks), chunks
    client = initialize_tracing()
    client.flush()
    workspace = configured_workspace()
    deadline = time.time() + 90
    try:
        while time.time() < deadline:
            rows = workspace.list('v2/observations', cursor=True, name='chattft-development-chat',
                                  fields='core,basic,time,io,metadata', fromStartTime=started)
            for row in rows:
                for field in ('input', 'output'):
                    if isinstance(row.get(field), str):
                        try:
                            row[field] = json.loads(row[field])
                        except json.JSONDecodeError:
                            pass
            matches = [row for row in rows if row.get('input') == {'messages': messages} and row.get('output') == 'Mock application reply.']
            if matches:
                root = max(matches, key=lambda row: row['startTime'])
                assert root['environment'] == 'development', root
                trace = workspace.list('v2/observations', cursor=True, traceId=root['traceId'], fields='core')
                assert any(row['type'] == 'GENERATION' for row in trace), trace
                atomic_write(Path('/tmp/chattft-development-trace.json'), canonical_json(root))
                print('Real development stream exported replayable messages and nested generation.')
                return
            await asyncio.sleep(2)
        raise AssertionError('Development trace did not persist before deadline')
    finally:
        workspace.close()
        client.shutdown()


if __name__ == '__main__':
    asyncio.run(main())
