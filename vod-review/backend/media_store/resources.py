"""Publish and retrieve immutable media, text, and data shared by both apps."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from .models import Resource
from .utils import configured_root, copy_resource, resource_digest, resource_from_row


class ResourceStore:
    """Use an additive artifact catalog without requiring media executables."""

    def __init__(self, root: Path):
        """Initialize resource schema v1 alongside the existing media schema."""
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "resources").mkdir(exist_ok=True)
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise RuntimeError(f"Unsupported shared media catalog version: {version}")
            # Separate versioning lets existing media-only clients keep working.
            connection.execute("CREATE TABLE IF NOT EXISTS resource_schema (version INTEGER NOT NULL)")
            versions = connection.execute("SELECT version FROM resource_schema").fetchall()
            if versions and versions != [(1,)]:
                raise RuntimeError("Unsupported shared resource catalog version")
            if not versions:
                connection.execute("INSERT INTO resource_schema VALUES (1)")
            connection.execute("CREATE TABLE IF NOT EXISTS resources (id TEXT PRIMARY KEY, kind TEXT NOT NULL, source TEXT NOT NULL, name TEXT NOT NULL, metadata TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS resource_source ON resources(source, kind)")

    @classmethod
    def from_env(cls) -> ResourceStore | None:
        """Use the same suite directory or explicit override as media downloads."""
        root = configured_root()
        return None if root is None else cls(root)

    @contextmanager
    def connection(self):
        """Commit short transactions and close connections on every exit."""
        connection = sqlite3.connect(self.root / "catalog.sqlite3", timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def publish(self, file: Path, *, kind: str, source: str, name: str | None = None,
                content_type: str = "application/octet-stream", metadata: dict | None = None) -> Resource:
        """Copy a completed artifact into immutable storage and return its reference.

        Args:
            file: Local completed file; the original is preserved.
            kind: Explicit modality: text, data, image, audio, or video.
            source: Shared logical identity, such as youtube:ID or analysis:NAME.
            name: Human-readable name, defaulting to the original filename.
            content_type: Representation MIME type, such as application/json.
            metadata: JSON provenance, schema, or related resource references.
        """
        if kind not in {"text", "data", "image", "audio", "video"}:
            raise ValueError("Unsupported resource kind")
        if not source.strip() or not content_type.strip():
            raise ValueError("Source and content type must be nonempty")
        file = Path(file)
        if not file.is_file():
            raise FileNotFoundError(file)
        metadata = json.loads(json.dumps({} if metadata is None else metadata, allow_nan=False))
        if not isinstance(metadata, dict):
            raise ValueError("Resource metadata must be a JSON object")
        resource_id = uuid.uuid4().hex
        destination = self.root / "resources" / resource_id
        temporary = destination.with_suffix(".tmp")
        try:
            copy_resource(file, temporary, self.root)
            digest = resource_digest(temporary)
            resource = Resource(resource_id, kind, source, name or file.name,
                                content_type, temporary.stat().st_size, digest, metadata)
            temporary.replace(destination)
            with self.connection() as connection:
                connection.execute("INSERT INTO resources VALUES (?,?,?,?,?)", (
                    resource_id, kind, source, resource.name, json.dumps(asdict(resource))))
            return resource
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, reference: str) -> Resource:
        """Resolve a stable ID or tft-resource:ID, rejecting unknown references."""
        resource_id = reference.removeprefix("tft-resource:")
        with self.connection() as connection:
            row = connection.execute("SELECT metadata FROM resources WHERE id=?", (resource_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown resource: {reference}")
        return resource_from_row(row[0])

    def find(self, *, source: str | None = None, kind: str | None = None,
             name: str | None = None, limit: int = 100, offset: int = 0) -> list[Resource]:
        """Discover references using exact filters, newest first, with pagination."""
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("Limit must be 1..1000 and offset must be nonnegative")
        filters = {key: value for key, value in {"source": source, "kind": kind, "name": name}.items() if value is not None}
        where = " AND ".join(key + "=?" for key in filters) or "1=1"
        with self.connection() as connection:
            rows = connection.execute("SELECT metadata FROM resources WHERE " + where + " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                                      [*filters.values(), limit, offset]).fetchall()
        return [resource_from_row(row[0]) for row in rows]

    def resolve(self, reference: str) -> Path:
        """Return the shared path only after verifying size and SHA-256 integrity."""
        resource = self.get(reference)
        path = self.root / "resources" / resource.id
        if not path.is_file():
            raise FileNotFoundError(f"Missing shared resource: {reference}")
        if path.stat().st_size != resource.size or resource_digest(path) != resource.sha256:
            raise ValueError(f"Shared resource failed integrity check: {reference}")
        return path

    def pull(self, reference: str, destination: Path) -> Path:
        """Copy a verified artifact locally without replacing an existing file."""
        source = self.resolve(reference)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Publish the complete copy with an exclusive link, avoiding partial
        # destination files and preserving existing caller-owned files.
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copyfile(source, temporary)
            os.link(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def read_text(self, reference: str, *, max_bytes: int = 10_000_000) -> str:
        """Read bounded UTF-8 text or structured text data from a reference."""
        resource = self.get(reference)
        if resource.kind not in {"text", "data"}:
            raise ValueError("Resource is not text or data")
        if max_bytes < 0 or resource.size > max_bytes:
            raise ValueError("Resource exceeds the read limit; use resolve or pull")
        return self.resolve(reference).read_text(encoding="utf-8")

    def read_json(self, reference: str, *, max_bytes: int = 10_000_000):
        """Decode a bounded JSON artifact without executing serialized code."""
        return json.loads(self.read_text(reference, max_bytes=max_bytes))
