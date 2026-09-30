"""Local Google OAuth routes and background round-upload operations."""

import asyncio
import secrets
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

try:
    from .. import db
except ImportError:  # Support uvicorn app:app from the backend directory.
    import db
from .models import DriveUploadOptions, UploadJob
from .utils import (SCOPE, access_token, connection_status, create_folder, exchange_token, oauth_config,
                    render_clip, round_clips, save_token, upload_clip)

router = APIRouter()
STATES: dict[str, float] = {}
JOBS: dict[str, UploadJob] = {}


@router.get("/api/gdrive/status")
def google_status() -> dict:
    """Let a returning browser recognize completed Google authorization."""
    return connection_status()


@router.get("/api/gdrive/connect")
def connect_google() -> RedirectResponse:
    """Start browser authorization with a short-lived, browser-bound state."""
    config = oauth_config()
    now = time.monotonic()
    for state, expiry in list(STATES.items()):
        if expiry < now:
            STATES.pop(state, None)
    state = secrets.token_urlsafe(32)
    STATES[state] = now + 600
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": config["client_id"], "redirect_uri": config["redirect_uri"],
        "response_type": "code", "scope": SCOPE, "access_type": "offline",
        "prompt": "consent", "state": state,
    })
    response = RedirectResponse(url)
    response.set_cookie("vod_gdrive_state", state, httponly=True, samesite="lax", max_age=600,
                        secure=config["redirect_uri"].startswith("https://"), path="/api/gdrive")
    return response


@router.get("/api/gdrive/callback")
def google_callback(request: Request, state: str = "", code: str = "", error: str = "") -> HTMLResponse:
    """Validate the authorizing browser and keep all Google tokens server-side."""
    cookie = request.cookies.get("vod_gdrive_state", "")
    if not state or not secrets.compare_digest(state, cookie) or STATES.pop(state, 0) < time.monotonic():
        raise HTTPException(400, "Google authorization expired or did not match this browser. Connect again.")
    if error or not code:
        raise HTTPException(400, "Google Drive access was not granted. You can reconnect when ready.")
    token = exchange_token({**oauth_config(), "code": code, "grant_type": "authorization_code"})
    if not token.get("refresh_token"):
        raise HTTPException(400, "Google did not grant offline access. Reconnect Google Drive.")
    save_token({"refresh_token": token["refresh_token"]})
    response = HTMLResponse("<h1>Google Drive connected</h1><p>Return to VOD Review and click Upload to GDrive. You can close this tab.</p>")
    response.delete_cookie("vod_gdrive_state", path="/api/gdrive")
    response.headers["Cache-Control"] = "no-store"
    return response


def run_upload(job: UploadJob, source: Path, name: str) -> None:
    """Encode and upload sequentially, retaining progress for a failed-batch retry."""
    try:
        if not source.is_file():
            raise HTTPException(404, "The source video is missing.")
        if not job.folder_id:
            job.folder_id = create_folder(f"{name} — round clips", access_token())
        # One temporary clip at a time bounds local storage even for long VODs.
        with tempfile.TemporaryDirectory(prefix="vod-gdrive-") as directory:
            while job.completed < len(job.clips):
                index = job.completed
                clip = job.clips[index]
                path = Path(directory) / f"{index + 1:04d}-round-{clip['label']}-{clip['start']:.3f}s.mp4"
                render_clip(source, path, clip)
                uploaded = upload_clip(path, job.folder_id, access_token(), f"{job.id}-{index}")
                job.files.append(uploaded)
                job.completed += 1
                path.unlink(missing_ok=True)
        job.status = "completed"
    except Exception as exc:
        job.error = str(exc.detail) if isinstance(exc, HTTPException) else "Upload failed. Check server configuration and retry."
        job.status = "failed"


@router.post("/api/videos/{video_id}/gdrive-upload")
async def start_upload(video_id: str, request: Request, background: BackgroundTasks, options: DriveUploadOptions) -> dict:
    """Start all parsed rounds or resume a failed batch without client timestamps."""
    # Require a preflighted JSON request: unrelated web pages must not trigger
    # uploads through a simple cross-origin form POST to this local service.
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise HTTPException(415, "Upload requests must use application/json.")
    video = db.get_video(video_id)
    clips = round_clips(video, options)
    source = db.video_path(video_id)
    if not source.is_file():
        raise HTTPException(404, "The source video is missing.")
    await asyncio.to_thread(access_token)
    # Recheck after authorization's await: concurrent clicks must share one job.
    previous = JOBS.get(video_id)
    if previous and previous.status == "running":
        return previous.payload()
    if previous and previous.classification_id == video["current_job"]["id"] and previous.options == options:
        if previous.status == "completed":
            return previous.payload()
        job = previous
        job.status, job.error = "running", None
    else:
        job = UploadJob(uuid.uuid4().hex, video_id, video["current_job"]["id"], clips, options=options)
        JOBS[video_id] = job
    background.add_task(run_upload, job, source, Path(video["original_name"]).stem)
    return job.payload()


@router.get("/api/videos/{video_id}/gdrive-upload")
def upload_status(video_id: str) -> dict | None:
    """Let the UI recover upload progress after switching videos or reloading."""
    db.get_video(video_id)
    job = JOBS.get(video_id)
    return job.payload() if job else None
