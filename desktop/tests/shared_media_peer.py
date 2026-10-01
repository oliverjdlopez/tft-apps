"""Exercise one real app's media boundary in its independently installed interpreter."""

import base64
import json
from pathlib import Path
import sys
from unittest.mock import patch


def main() -> None:
    """Perform one offline operation; deliberately do not run application lifespans."""
    from fastapi.testclient import TestClient

    operation = json.load(sys.stdin)
    if operation["app"] == "chat":
        from api.app import app
        from scripts.transcription.media_store import MediaStore
        from scripts.transcription.media_store.models import MediaRequest
    else:
        from backend import app as app_module, db
        from backend.media_store import MediaStore
        from backend.media_store.models import MediaRequest

        db.init_db()
        # Verify the import boundary without starting unrelated playback jobs.
        app_module.start_playback_preparation = lambda _: None
        app = app_module.app

    if operation.get("action") == "media_import":
        store = MediaStore.from_env()
        path = store.obtain(MediaRequest("https://youtu.be/exchange", kind="video",
                                         profile="video:720p", playable=True),
                            lambda: Path(operation["file"]))
        result = {"path": str(path)}
    elif operation.get("action") == "cached_transcription":
        from scripts.transcription.download_vod import DownloadConfig, download_vod

        with patch("scripts.transcription.download_vod.download_vod_local",
                   side_effect=AssertionError("A cached VOD must not be downloaded again")):
            download = download_vod(DownloadConfig("https://youtube.com/watch?v=exchange"))
        result = {"path": str(download.media_path)}
    elif operation.get("action") == "cached_audio":
        with patch.object(app_module, "download_audio_url_local",
                          side_effect=AssertionError("VOD must reuse the cached audio stream")):
            path = app_module.download_audio_url("https://youtu.be/exchange", "audio-task")
        result = {"path": str(path)}
    else:
        client = TestClient(app)
        response = client.request(
            operation["method"], operation["url"], params=operation.get("params"),
            content=base64.b64decode(operation["body"]) if "body" in operation else None,
            json=operation.get("json"), headers=operation.get("headers"),
        )
        result = {"status": response.status_code}
        if operation.get("binary"):
            result["body"] = base64.b64encode(response.content).decode()
        elif response.content:
            result["json"] = response.json()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
