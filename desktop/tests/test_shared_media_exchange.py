"""Prove bidirectional sharing between the suite's independently installed backends."""

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

SUITE = Path(__file__).resolve().parents[2]


def peer(tmp_path: Path, app: str, **operation) -> dict:
    """Run the real backend boundary in its own environment with disposable state."""
    root = SUITE / ("tft-chat" if app == "chat" else "vod-review")
    environment = {**os.environ, "TFT_MEDIA_DIR": str(tmp_path / "shared"),
                   "VOD_DATA_DIR": str(tmp_path / "vod"),
                   "PYTHONPATH": os.pathsep.join(map(str, [root, root / "app/backend", root / "app/backend/src"]))}
    result = subprocess.run(
        [str(root / ".venv/bin/python"), str(Path(__file__).with_name("shared_media_peer.py"))],
        input=json.dumps({"app": app, **operation}), cwd=root, env=environment,
        check=True, capture_output=True, text=True, timeout=30,
    )
    return json.loads(result.stdout)


def test_both_http_backends_discover_and_read_each_others_publications(tmp_path):
    """References published in either process resolve identically in the other."""
    for publisher, consumer, kind, content, mime in [
        ("vod", "chat", "image", b"image bytes", "image/png"),
        ("chat", "vod", "data", b'{"round":"2-1"}', "application/json"),
    ]:
        published = peer(tmp_path, publisher, method="POST", url="/api/shared-media",
                         params={"kind": kind, "source": publisher, "name": "artifact"},
                         body=base64.b64encode(content).decode(), headers={"content-type": mime})
        assert published["status"] == 201
        resource = published["json"]
        discovered = peer(tmp_path, consumer, method="GET", url="/api/shared-media", params={"source": publisher})
        assert discovered["json"] == [resource]
        downloaded = peer(tmp_path, consumer, method="GET", url=resource["content_url"], binary=True)
        assert downloaded["status"] == 200
        assert base64.b64decode(downloaded["body"]) == content


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="requires local media tools")
def test_shared_download_reuse_and_chat_video_import_into_vod(tmp_path):
    """Reuse VOD audio in ChatTFT and retain a Chat-published video after review deletion."""
    video = tmp_path / "sample.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=s=64x64:d=1",
                    "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(video)], check=True)
    registered = peer(tmp_path, "vod", action="media_import", file=str(video))
    reused = peer(tmp_path, "chat", action="cached_transcription")
    assert reused["path"] == registered["path"]
    assert peer(tmp_path, "vod", action="cached_audio")["path"] == registered["path"]
    resources = peer(tmp_path, "chat", method="GET", url="/api/shared-media", params={"source": "youtube:exchange"})
    assert len(resources["json"]) == 1
    cached = resources["json"][0]
    assert cached["kind"] == "video"
    cached_bytes = peer(tmp_path, "chat", method="GET", url=cached["content_url"], binary=True)
    assert base64.b64decode(cached_bytes["body"]) == video.read_bytes()
    published = peer(tmp_path, "chat", method="POST", url="/api/shared-media",
                     params={"kind": "video", "source": "chat:upload", "name": "sample.mp4"},
                     body=base64.b64encode(video.read_bytes()).decode(), headers={"content-type": "video/mp4"})
    resource = published["json"]
    imported = peer(tmp_path, "vod", method="POST", url="/api/videos/shared", json={"reference": resource["reference"]})
    assert imported["status"] == 201
    assert imported["json"]["original_name"] == "sample.mp4"
    deleted = peer(tmp_path, "vod", method="DELETE", url=f'/api/videos/{imported["json"]["id"]}')
    assert deleted["status"] == 204
    read_after_delete = peer(tmp_path, "chat", method="GET", url=resource["content_url"], binary=True)
    assert base64.b64decode(read_after_delete["body"]) == video.read_bytes()


def test_vendored_protocols_remain_identical():
    """Prevent independently installed apps from silently diverging on the shared schema."""
    chat = SUITE / "tft-chat/scripts/transcription/media_store"
    vod = SUITE / "vod-review/backend/media_store"
    assert {path.name for path in chat.glob("*.py")} == {path.name for path in vod.glob("*.py")}
    for path in chat.glob("*.py"):
        assert path.read_bytes() == (vod / path.name).read_bytes(), path.name


def test_standalone_backends_default_to_the_same_suite_storage(tmp_path):
    """Resolve the default in both environments without creating runtime data."""
    environment = dict(os.environ)
    environment.pop("TFT_MEDIA_DIR", None)
    for app, module in [("tft-chat", "scripts.transcription.media_store.utils"),
                        ("vod-review", "backend.media_store.utils")]:
        root = SUITE / app
        result = subprocess.run(
            [str(root / ".venv/bin/python"), "-c", f"from {module} import configured_root; print(configured_root())"],
            cwd=tmp_path, env={**environment, "PYTHONPATH": str(root)},
            check=True, capture_output=True, text=True, timeout=10,
        )
        assert Path(result.stdout.strip()) == SUITE / "media"
