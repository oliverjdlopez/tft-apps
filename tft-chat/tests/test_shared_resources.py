"""Exercise artifact exchange, integrity, concurrency, and legacy compatibility."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from scripts.transcription.media_store.resources import ResourceStore


def test_exchange_and_immutable_references(tmp_path):
    """Independent clients find and pull prior versions even after republication."""
    first = ResourceStore(tmp_path / "shared")
    second = ResourceStore(tmp_path / "shared")
    original = tmp_path / "rounds.json"
    original.write_text('{"rounds": ["2-1"]}')
    resource = first.publish(original, kind="data", source="youtube:abc",
                             content_type="application/json", metadata={"producer": "vod-review"})
    original.write_text('{"rounds": ["3-1"]}')
    newer = first.publish(original, kind="data", source="youtube:abc")
    assert second.read_json(resource.reference) == {"rounds": ["2-1"]}
    assert second.find(source="youtube:abc", kind="data") == [newer, resource]
    assert second.find(source="other") == []
    assert second.find(limit=1, offset=1) == [resource]
    destination = second.pull(resource.reference, tmp_path / "local" / "rounds.json")
    assert json.loads(destination.read_text()) == {"rounds": ["2-1"]}
    with pytest.raises(FileExistsError):
        second.pull(newer.reference, destination)
    assert second.get(resource.id).metadata == {"producer": "vod-review"}


def test_missing_corrupt_and_bounded_reads(tmp_path):
    """Never return missing, oversized, or silently corrupted data as valid."""
    store = ResourceStore(tmp_path / "shared")
    original = tmp_path / "notes.txt"
    original.write_text("hello")
    resource = store.publish(original, kind="text", source="review:1")
    with pytest.raises(ValueError, match="read limit"):
        store.read_text(resource.reference, max_bytes=4)
    path = store.resolve(resource.reference)
    path.write_text("other")
    with pytest.raises(ValueError, match="integrity"):
        store.resolve(resource.reference)
    path.unlink()
    with pytest.raises(FileNotFoundError):
        store.resolve(resource.reference)
    with pytest.raises(KeyError):
        store.resolve("../../outside")


def test_concurrent_initialization_and_publication(tmp_path):
    """Concurrent clients initialize once and retain every published artifact."""
    original = tmp_path / "notes.txt"
    original.write_text("hello")

    def publish(index):
        """Create an independent connection and publish a named snapshot."""
        return ResourceStore(tmp_path / "shared").publish(original, kind="text", source="review:1", name=str(index))

    with ThreadPoolExecutor(max_workers=6) as executor:
        resources = list(executor.map(publish, range(12)))
    store = ResourceStore(tmp_path / "shared")
    assert len(store.find()) == len(resources)
    assert all(store.read_text(item.reference) == "hello" for item in resources)


def test_no_ffmpeg_or_configuration_required_for_import(tmp_path, monkeypatch):
    """Text storage works without media binaries, with explicit disable/override."""
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("TFT_MEDIA_DIR", "")
    assert ResourceStore.from_env() is None
    monkeypatch.setenv("TFT_MEDIA_DIR", "relative")
    with pytest.raises(ValueError, match="absolute"):
        ResourceStore.from_env()
    monkeypatch.setenv("TFT_MEDIA_DIR", str(tmp_path / "shared"))
    assert ResourceStore.from_env().find() == []


def test_cli_process_exchange(tmp_path):
    """A new CLI process can discover and pull another process's publication."""
    original = tmp_path / "notes.md"
    original.write_text("# Notes\n")
    environment = {**os.environ, "TFT_MEDIA_DIR": str(tmp_path / "shared")}
    command = [sys.executable, "-m", "scripts.transcription.media_store.resource_cli"]
    published = subprocess.run(command + ["publish", str(original), "--kind", "text", "--source", "review:1"], env=environment, check=True, capture_output=True, text=True)
    reference = json.loads(published.stdout)["reference"]
    destination = tmp_path / "pulled.md"
    subprocess.run(command + ["pull", reference, str(destination)], env=environment, check=True, capture_output=True)
    assert destination.read_text() == original.read_text()


def test_media_catalog_coexists_and_future_versions_fail(tmp_path):
    """Resource tables preserve legacy media rows and reject unknown protocols."""
    import sqlite3

    root = tmp_path / "shared"
    root.mkdir()
    with sqlite3.connect(root / "catalog.sqlite3") as connection:
        connection.execute("PRAGMA user_version=1")
        connection.execute("CREATE TABLE media_assets (id TEXT PRIMARY KEY, source TEXT, metadata TEXT)")
        connection.execute("INSERT INTO media_assets VALUES ('old', 'youtube:abc', '{}')")
    ResourceStore(root)
    with sqlite3.connect(root / "catalog.sqlite3") as connection:
        assert connection.execute("SELECT id FROM media_assets").fetchone() == ("old",)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)
        connection.execute("UPDATE resource_schema SET version=2")
    with pytest.raises(RuntimeError, match="Unsupported"):
        ResourceStore(root)
