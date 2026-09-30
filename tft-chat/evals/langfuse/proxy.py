"""Forward Docker webhooks to the host runner over a shared Unix socket."""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from .utils import close_proxy_stream

app = FastAPI(title="ChatTFT experiment forwarding")


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def forward(request: Request, path: str) -> Response:
    """Relay experiment requests without executing application or database code.

    Args:
        request: Original request, including the runner's bearer credential.
        path: Runner route relative to the fixed Unix-socket destination.

    Returns:
        Runner response, or a bounded service-unavailable response.
    """
    if path not in {"health", "experiments", "v1/models", "v1/chat/completions"} and not path.startswith("jobs/"):
        return Response(status_code=404)
    transport = httpx.AsyncHTTPTransport(uds=os.environ.get("LANGFUSE_RUNNER_SOCKET", "/runtime/runner.sock"))
    if path == "v1/chat/completions":
        client = httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(200, connect=5))
        try:
            upstream = client.build_request(request.method, f"http://runner/{path}",
                headers={"authorization": request.headers.get("authorization", ""), "content-type": "application/json"},
                content=await request.body())
            result = await client.send(upstream, stream=True)
            return StreamingResponse(result.aiter_bytes(), status_code=result.status_code,
                media_type=result.headers.get("content-type", "application/json"),
                background=BackgroundTask(close_proxy_stream, result, client))
        except httpx.HTTPError:
            await client.aclose()
            return Response('{"error":{"message":"Host ChatTFT runner unavailable"}}', status_code=503,
                            media_type="application/json")
    try:
        async with httpx.AsyncClient(transport=transport, timeout=18) as client:
            result = await client.request(request.method, f"http://runner/{path}",
                headers={"authorization": request.headers.get("authorization", ""),
                         "content-type": request.headers.get("content-type", "application/json")},
                content=await request.body())
        return Response(result.content, status_code=result.status_code,
                        media_type=result.headers.get("content-type", "application/json"))
    except httpx.HTTPError:
        return Response('{"detail":"Host experiment runner unavailable; run chat-tft-evals up"}',
                        status_code=503, media_type="application/json")
