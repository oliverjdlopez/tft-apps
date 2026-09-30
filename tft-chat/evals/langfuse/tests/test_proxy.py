"""Exercise the fixed socket destination and authenticated webhook forwarding."""
import asyncio
from unittest.mock import patch

import httpx
from starlette.requests import Request

from evals.langfuse.proxy import forward


def test_proxy_preserves_authentication_body_and_response():
    """A webhook reaches the runner unchanged and preserves validation failures."""
    async def exercise():
        """Supply in-memory ASGI input and a mock Unix-socket transport."""
        async def receive():
            """Deliver the native experiment request body."""
            return {'type': 'http.request', 'body': b'{"datasetName":"chat"}'}

        def handle(request):
            """Verify the forwarded credential without sending network traffic."""
            assert request.headers['authorization'] == 'Bearer test-token'
            assert request.content == b'{"datasetName":"chat"}'
            assert str(request.url) == 'http://runner/experiments'
            return httpx.Response(422, json={'detail': 'invalid case'})

        request = Request({'type': 'http', 'method': 'POST', 'headers': [(b'authorization', b'Bearer test-token')]}, receive)
        with patch('evals.langfuse.proxy.httpx.AsyncHTTPTransport', return_value=httpx.MockTransport(handle)):
            response = await forward(request, 'experiments')
        assert response.status_code == 422
        assert b'invalid case' in response.body
    asyncio.run(exercise())


def test_missing_runner_is_service_unavailable():
    """A stopped host runner produces an actionable 503 instead of false readiness."""
    async def exercise():
        """Simulate connection refusal without needing a running host service."""
        async def receive():
            """Provide an empty health request body."""
            return {'type': 'http.request', 'body': b''}

        def handle(request):
            """Represent a missing Unix socket."""
            raise httpx.ConnectError('unavailable')

        request = Request({'type': 'http', 'method': 'GET', 'headers': []}, receive)
        with patch('evals.langfuse.proxy.httpx.AsyncHTTPTransport', return_value=httpx.MockTransport(handle)):
            response = await forward(request, 'health')
        assert response.status_code == 503
    asyncio.run(exercise())


def test_proxy_relays_completion_stream_and_closes_transport():
    """Long graph completions retain SSE framing through the Docker proxy."""
    async def exercise():
        """Verify the fixed upstream route and streamed response lifecycle."""
        async def receive():
            """Supply an authenticated native completion request."""
            return {'type': 'http.request', 'body': b'{"stream":true}'}

        def handle(request):
            """Return an SSE frame without buffering inside the proxy."""
            assert str(request.url) == 'http://runner/v1/chat/completions'
            assert request.headers['authorization'] == 'Bearer test-token'
            return httpx.Response(200, content=b'data: [DONE]\n\n', headers={'content-type': 'text/event-stream'})

        request = Request({'type': 'http', 'method': 'POST', 'headers': [(b'authorization', b'Bearer test-token')]}, receive)
        with patch('evals.langfuse.proxy.httpx.AsyncHTTPTransport', return_value=httpx.MockTransport(handle)):
            response = await forward(request, 'v1/chat/completions')
            assert response.status_code == 200
            assert b''.join([chunk async for chunk in response.body_iterator]) == b'data: [DONE]\n\n'
            await response.background()
    asyncio.run(exercise())
