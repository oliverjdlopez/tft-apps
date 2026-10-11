"""Verify resource transfers and independent review lifetimes through the VOD API."""

from fastapi.testclient import TestClient
import pytest

from backend import app, db
from backend.media_store.resources import ResourceStore
from backend.media_store import router as resources_api
from backend.tests.test_api import make_video


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Use only temporary catalogue/database state and skip playback workers."""
    monkeypatch.setenv("TFT_MEDIA_DIR", str(tmp_path / "shared"))
    for name, value in {"DATA_DIR": tmp_path / "vod", "VIDEO_DIR": tmp_path / "vod/videos",
                        "DOWNLOAD_DIR": tmp_path / "vod/downloads",
                        "DB_PATH": tmp_path / "vod/vod.sqlite3"}.items():
        monkeypatch.setattr(db, name, value)
    db.init_db()
    monkeypatch.setattr(app, "start_playback_preparation", lambda _: None)
    return TestClient(app.app)


def test_upload_share_import_and_delete_preserve_shared_bytes(client, tmp_path):
    """Publish a review, create a separate review from its reference, and delete both."""
    video = tmp_path / "sample.mp4"
    make_video(video)
    response = client.post("/api/videos", files={"file": ("sample.mp4", video.read_bytes(), "video/mp4")})
    assert response.status_code == 201
    original_id = response.json()["id"]
    shared = client.post(f"/api/videos/{original_id}/share")
    assert shared.status_code == 201
    resource = shared.json()
    assert resource["reference"].startswith("tft-resource:")
    imported = client.post("/api/videos/shared", json={"reference": resource["reference"]})
    assert imported.status_code == 201
    imported_id = imported.json()["id"]
    assert imported_id != original_id
    assert db.video_is_shared(imported_id)
    assert db.video_path(imported_id) != db.video_path(original_id)
    for video_id in (original_id, imported_id):
        assert client.delete(f"/api/videos/{video_id}").status_code == 204
    assert client.get(resource["content_url"]).content == video.read_bytes()


def test_raw_publication_ranges_filters_and_validation(client):
    """Both catalogue access and partial byte reads have stable HTTP contracts."""
    published = client.post("/api/shared-media", params={"kind": "text", "source": "review:1", "name": "notes.txt"},
                            content=b"hello world", headers={"content-type": "text/plain"})
    assert published.status_code == 201
    resource = published.json()
    assert "path" not in resource
    assert client.get("/api/shared-media", params={"source": "review:1"}).json() == [resource]
    assert client.get("/api/shared-media", params={"source": "other"}).json() == []
    response = client.get(resource["content_url"], headers={"range": "bytes=0-4"})
    assert response.status_code == 206
    assert response.content == b"hello"
    assert client.post("/api/videos/shared", json={"reference": resource["reference"]}).status_code == 422
    assert client.post("/api/videos/shared", json={"reference": resource["reference"], "path": "/private"}).status_code == 422
    assert client.get("/api/shared-media/unknown/content").status_code == 404
    assert client.get("/api/shared-media", params={"limit": 1001}).status_code == 422


def test_corrupt_missing_and_disabled_resources_fail_explicitly(client, tmp_path, monkeypatch):
    """Avoid serving corrupt bytes or falling back silently to local storage."""
    original = tmp_path / "notes.txt"
    original.write_text("hello")
    store = ResourceStore(tmp_path / "shared")
    resource = store.publish(original, kind="text", source="review:1")
    path = store.resolve(resource.reference)
    path.write_text("other")
    url = f"/api/shared-media/{resource.reference}/content"
    assert client.get(url).status_code == 409
    path.unlink()
    assert client.get(url).status_code == 410
    monkeypatch.setenv("TFT_MEDIA_DIR", "")
    assert client.get("/api/shared-media").status_code == 503


def test_oversized_upload_is_cleaned_up(client, tmp_path, monkeypatch):
    """A rejected streaming upload leaves no file or catalogue entry behind."""
    monkeypatch.setattr(resources_api, "MAX_UPLOAD_BYTES", 3)
    result = client.post("/api/shared-media", params={"kind": "text", "source": "x", "name": "x"}, content=b"1234")
    assert result.status_code == 413
    assert client.get("/api/shared-media").json() == []
    assert not list((tmp_path / "shared").glob("upload-*"))


def test_video_import_validates_actual_bytes(client):
    """A claimed modality cannot turn a non-video artifact into a review record."""
    publication = client.post("/api/shared-media", params={"kind": "video", "source": "example", "name": "bad.mp4"},
                              content=b"not a video", headers={"content-type": "video/mp4"})
    assert publication.status_code == 201
    response = client.post("/api/videos/shared", json={"reference": publication.json()["reference"]})
    assert response.status_code == 400
    assert db.list_videos() == []
