"""Publish and retrieve shared artifacts from either independent backend."""

from pathlib import Path
import sqlite3
import tempfile
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .resources import ResourceStore
from .utils import resource_errors, resource_payload

router = APIRouter(prefix="/api/shared-media", tags=["shared-media"])
MAX_UPLOAD_BYTES = 5 * 1024 ** 3
ResourceKind = Literal["text", "data", "image", "audio", "video"]


def required_store() -> ResourceStore:
    """Open the configured store, reporting disabled or unavailable storage."""
    try:
        store = ResourceStore.from_env()
    except (ValueError, RuntimeError, OSError, sqlite3.Error):
        raise HTTPException(503, "Shared media storage is unavailable") from None
    if store is None:
        raise HTTPException(503, "Shared media storage is disabled")
    return store


@router.get("")
def list_resources(source: str | None = None, kind: ResourceKind | None = None,
                   name: str | None = None, limit: int = Query(100, ge=1, le=1000),
                   offset: int = Query(0, ge=0)) -> list[dict]:
    """Discover shared files by exact provenance filters with bounded pagination."""
    return [resource_payload(item) for item in required_store().find(
        source=source, kind=kind, name=name, limit=limit, offset=offset)]


@router.post("", status_code=201)
async def publish_resource(request: Request, kind: ResourceKind,
                           source: str = Query(min_length=1, max_length=2048),
                           name: str = Query(min_length=1, max_length=255)) -> dict:
    """Stream the raw request body into immutable storage without loading it in RAM.

    Args:
        request: Binary body; Content-Type records the representation MIME type.
        kind: Explicit resource modality.
        source: Shared logical identity supplied by the publisher.
        name: Display/download filename, never a server filesystem path.

    Returns:
        Metadata, stable reference, and a content URL usable at either backend.
    """
    if not source.strip() or not name.strip():
        raise HTTPException(422, "Source and name must be nonempty")
    store = await run_in_threadpool(required_store)
    # Temporary files live on the same disk and are cleaned up on disconnect,
    # failure, or completion. No HTTP operation accepts local filesystem paths.
    with tempfile.TemporaryDirectory(prefix="upload-", dir=store.root) as directory:
        temporary = Path(directory) / "body"
        size = 0
        with temporary.open("wb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Shared media upload exceeds 5 GiB")
                await run_in_threadpool(output.write, chunk)
        with resource_errors():
            resource = await run_in_threadpool(
                store.publish, temporary, kind=kind, source=source, name=name,
                content_type=request.headers.get("content-type", "application/octet-stream"),
            )
        return resource_payload(resource)


@router.get("/{reference}")
def get_resource(reference: str) -> dict:
    """Inspect a stable resource reference through either backend."""
    with resource_errors():
        return resource_payload(required_store().get(reference))


@router.get("/{reference}/content")
def resource_content(reference: str) -> FileResponse:
    """Serve verified bytes with HTTP range support for media playback."""
    store = required_store()
    with resource_errors():
        resource = store.get(reference)
        path = store.resolve(reference)
    return FileResponse(path, media_type=resource.content_type, filename=resource.name,
                        headers={"X-Content-Type-Options": "nosniff"})
