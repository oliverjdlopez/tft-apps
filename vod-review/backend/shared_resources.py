"""Connect app-owned VOD reviews to portable shared media references."""

import asyncio
import uuid

from fastapi import APIRouter, HTTPException

try:
    from . import db
    from .media_store.router import required_store
    from .media_store.utils import resource_errors, resource_payload
    from .models import SharedVideoRequest
except ImportError:  # Support the documented backend-directory launch.
    import db
    from media_store.router import required_store
    from media_store.utils import resource_errors, resource_payload
    from models import SharedVideoRequest

router = APIRouter(prefix="/api/videos", tags=["shared-media"])


def publish_video(video_id: str) -> dict:
    """Copy an existing VOD into the catalogue while preserving its review state."""
    video = db.get_video(video_id)
    with resource_errors():
        resource = required_store().publish(
            db.video_path(video_id), kind="video", source="vod-review:" + video_id,
            name=video["original_name"], content_type=video["mime_type"],
            metadata={"video_id": video_id},
        )
    return resource_payload(resource)


def import_video(reference: str) -> dict:
    """Create an independent review pointing to verified shared video bytes."""
    try:
        from .app import probe_video
    except ImportError:
        from app import probe_video

    store = required_store()
    with resource_errors():
        resource = store.get(reference)
        if resource.kind != "video":
            raise HTTPException(422, "The shared resource must be a video")
        path = store.resolve(reference)
        metadata = probe_video(path)
    return db.create_video(
        uuid.uuid4().hex, resource.name, path, resource.content_type,
        metadata["duration"], metadata["width"], metadata["height"], shared_media=True,
    )


@router.post("/{video_id}/share", status_code=201)
def share_video(video_id: str) -> dict:
    """Publish an uploaded or downloaded review video for the other backend."""
    return publish_video(video_id)


@router.post("/shared", status_code=201)
async def create_shared_video(request: SharedVideoRequest) -> dict:
    """Import a shared video and start the ordinary playback preparation path."""
    try:
        from .app import start_playback_preparation
    except ImportError:
        from app import start_playback_preparation

    video = await asyncio.to_thread(import_video, request.reference)
    start_playback_preparation(video["id"])
    return video
