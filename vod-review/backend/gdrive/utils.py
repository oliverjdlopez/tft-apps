"""Google protocol, credential storage, and clip helpers for the Drive router."""

import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import HTTPException

from .models import DriveUploadOptions

SCOPE = "https://www.googleapis.com/auth/drive.file"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_URL = "https://www.googleapis.com/drive/v3/files"


def oauth_config() -> dict:
    """Load a Google web-client JSON file configured for this local backend."""
    path = os.environ.get("VOD_GDRIVE_CLIENT_FILE")
    if not path:
        raise HTTPException(503, "Set VOD_GDRIVE_CLIENT_FILE to a Google OAuth web-client JSON file; see docs/google-drive.md.")
    try:
        config = json.loads(Path(path).read_text())["web"]
        return {"client_id": config["client_id"], "client_secret": config["client_secret"],
                "redirect_uri": os.environ.get("VOD_GDRIVE_REDIRECT_URI", "http://localhost:8000/api/gdrive/callback")}
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Google Drive OAuth web-client configuration is invalid.") from exc


def token_path() -> Path:
    """Keep OAuth refresh credentials outside the repository by default."""
    return Path(os.environ.get("VOD_GDRIVE_TOKEN_FILE", str(Path.home() / ".config/vod-review/gdrive-token.json")))


def connection_status() -> dict:
    """Report saved authorization without exposing credentials or calling Google.

    Returns:
        Whether a local refresh grant is saved; validity is checked on upload.
    """
    try:
        token = json.loads(token_path().read_text())
        connected = isinstance(token, dict) and isinstance(token.get("refresh_token"), str) and bool(token["refresh_token"])
    except (OSError, ValueError):
        connected = False
    return {"connected": connected}


def google_request(url: str, *, method: str = "GET", data: bytes | None = None,
                   headers: dict | None = None) -> tuple[dict, dict, int]:
    """Call Google with bounded waits and errors that never disclose credentials."""
    try:
        with urlopen(Request(url, data=data, headers=headers or {}, method=method), timeout=120) as response:
            body = response.read()
            return (json.loads(body) if body else {}, dict(response.headers), response.status)
    except HTTPError as exc:
        if exc.code == 308:
            return {}, dict(exc.headers), 308
        detail = "Google Drive request failed"
        if exc.code in (400, 401):
            detail += "; reconnect Google Drive if authorization has expired"
        elif exc.code == 403:
            detail += "; check Drive API access and available storage"
        raise HTTPException(502, f"{detail} (HTTP {exc.code}).") from None
    except (URLError, TimeoutError, ValueError) as exc:
        raise HTTPException(502, "Google Drive could not be reached or returned an invalid response. Retry the upload.") from exc


def exchange_token(fields: dict) -> dict:
    """Exchange a code or refresh token at Google's fixed token endpoint."""
    result, _, _ = google_request(TOKEN_URL, method="POST", data=urlencode(fields).encode(),
                                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    return result


def save_token(token: dict) -> None:
    """Atomically save refresh credentials with owner-only file permissions."""
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".gdrive-")
    try:
        with os.fdopen(descriptor, "w") as target:
            json.dump(token, target)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def access_token() -> str:
    """Refresh server-held authorization before sending media to Drive."""
    config = oauth_config()
    try:
        refresh = json.loads(token_path().read_text())["refresh_token"]
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(401, "Connect Google Drive first, then click Upload to GDrive.") from exc
    result = exchange_token({**config, "refresh_token": refresh, "grant_type": "refresh_token"})
    if not result.get("access_token"):
        raise HTTPException(401, "Reconnect Google Drive to authorize uploads.")
    return result["access_token"]


def round_clips(video: dict, options: DriveUploadOptions | None = None) -> list[dict]:
    """Build independent minute clips from all stored confirmed transitions.

    Args:
        video: Database video payload with its current completed classification.
        options: Round selection, signed start offset, and per-clip duration.

    Returns:
        Chronological clips, with only the source end shortening their duration.
    """
    options = options or DriveUploadOptions()
    job = video.get("current_job")
    if not job or job.get("status") != "completed":
        raise HTTPException(400, "Complete round classification before uploading.")
    clips = []
    seen = set()
    for result in sorted(job["results"], key=lambda item: item["timestamp_seconds"]):
        start = float(result["timestamp_seconds"])
        label = str(result["class_label"])
        if not math.isfinite(start) or start < 0 or start >= video["duration"] or start in seen:
            continue
        if not re.fullmatch(r"[1-7]-?[1-7]", label):
            continue
        stage, round_number = map(int, label.replace("-", ""))
        if options.key_rounds_only and not (stage == 1 or round_number == 1 or (stage in (3, 4) and round_number == 2)):
            continue
        seen.add(start)
        # Offset changes clip start, not the parsed round identity. Clamp to the
        # source start, and skip rounds whose shifted start lies past the end.
        start = max(0.0, start + options.offset_seconds)
        if start >= video["duration"]:
            continue
        clips.append({"label": label, "start": start, "duration": min(options.duration_seconds, video["duration"] - start)})
    if not clips:
        raise HTTPException(400, "No parsed rounds with available footage to upload.")
    return clips


def render_clip(source: Path, output: Path, clip: dict) -> None:
    """Seek and re-encode one accurate round start, retaining optional audio."""
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(clip["start"]),
               "-i", str(source), "-t", str(clip["duration"]), "-map", "0:v:0", "-map", "0:a:0?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-movflags", "+faststart", str(output)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=1800)
    except FileNotFoundError as exc:
        raise HTTPException(503, "Install ffmpeg on the backend to create round clips.") from exc
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise HTTPException(500, "Could not encode the round clip. Check the source video and ffmpeg installation.") from exc


def create_folder(name: str, token: str) -> str:
    """Create a private batch folder in the connected user's My Drive."""
    result, _, _ = google_request(DRIVE_URL, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=json.dumps({"name": name, "mimeType": "application/vnd.google-apps.folder"}).encode())
    return result["id"]


def upload_clip(path: Path, folder_id: str, token: str, key: str) -> dict:
    """Upload with bounded memory and recover already-created clips on retry."""
    headers = {"Authorization": f"Bearer {token}"}
    # A lost final response can leave a successful upload behind. Look up the
    # stable clip key before retrying so it is not uploaded a second time.
    query = urlencode({"q": f"'{folder_id}' in parents and trashed = false and appProperties has {{ key='roundClip' and value='{key}' }}",
                       "fields": "files(id,name)"})
    existing, _, _ = google_request(f"{DRIVE_URL}?{query}", headers=headers)
    if existing.get("files"):
        return existing["files"][0]
    size = path.stat().st_size
    _, response_headers, _ = google_request(
        "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&fields=id,name",
        method="POST", headers={**headers, "Content-Type": "application/json", "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps({"name": path.name, "parents": [folder_id], "appProperties": {"roundClip": key}}).encode())
    session = next((value for name, value in response_headers.items() if name.lower() == "location"), "")
    parsed = urlparse(session)
    if parsed.scheme != "https" or parsed.hostname != "www.googleapis.com":
        raise HTTPException(502, "Google Drive did not return a valid upload session.")
    with path.open("rb") as source:
        offset = 0
        while chunk := source.read(8 * 1024 * 1024):
            end = offset + len(chunk)
            result, chunk_headers, status = google_request(session, method="PUT", data=chunk,
                headers={**headers, "Content-Type": "video/mp4", "Content-Range": f"bytes {offset}-{end - 1}/{size}"})
            if end == size and status in (200, 201) and result.get("id"):
                return result
            if status != 308 or end == size:
                raise HTTPException(502, "Google Drive did not confirm the complete clip. Retry the upload.")
            acknowledged = next((value for name, value in chunk_headers.items() if name.lower() == "range"), "")
            if acknowledged != f"bytes=0-{end - 1}":
                raise HTTPException(502, "Google Drive did not acknowledge the full chunk. Retry the upload.")
            offset = end
    raise HTTPException(502, "Google Drive upload was incomplete.")
