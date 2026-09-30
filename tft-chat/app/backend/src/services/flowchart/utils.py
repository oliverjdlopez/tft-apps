"""Storage helpers for flowchart workspaces and saved groups: slugs, JSON files, and ORM mapping."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import tempfile

from db.models import DevFlowchartGroup, DevWorkspace
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    FlowchartFragment,
    GroupRecord,
    PatchWorkspace,
    WorkspaceConflictError,
    WorkspaceReadOnlyError,
    WorkspaceRecord,
    WorkspaceSource,
    WorkspaceSummary,
)

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

# ============================================================================
# Flowchart service
#
# Checked-in JSON workspaces are addressed by filename slug, so every path is
# derived from a validated slug and never from caller-supplied path segments.
# ============================================================================


def slugify(name: str) -> str:
    """Derive the ``gameplans/<slug>.json`` stem for a workspace name.

    Args:
        name: Player-facing workspace name.

    Returns:
        A lowercase hyphenated slug of at most 80 characters.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80].strip("-")
    return slug or "workspace"


def json_workspace_path(directory: Path, slug: str) -> Path:
    """Resolve a checked-in workspace file, rejecting anything but a plain slug.

    Args:
        directory: The ``gameplans/`` directory.
        slug: Workspace id used by the JSON source.

    Returns:
        The ``<slug>.json`` path inside ``directory``.

    Raises:
        LookupError: If ``slug`` is not a valid workspace slug.
    """
    if not SLUG_PATTERN.fullmatch(slug):
        raise LookupError("workspace not found")
    return directory / f"{slug}.json"


def json_workspace_paths(directory: Path) -> list[Path]:
    """List checked-in workspace files whose stems are valid slugs, sorted by name."""
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.glob("*.json")
        if path.is_file() and SLUG_PATTERN.fullmatch(path.stem)
    )


def record_from_file(path: Path) -> WorkspaceRecord:
    """Parse one checked-in workspace document into a read-only record.

    JSON files carry no revision history, so every file reports revision 1 and
    its modification time; the UI never saves back to this source.
    """
    workspace = PatchWorkspace.model_validate_json(path.read_text(encoding="utf-8"))
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return WorkspaceRecord(
        id=path.stem, revision=1, created_at=None, updated_at=modified,
        source="json", workspace=workspace,
    )


def record_from_row(row: DevWorkspace) -> WorkspaceRecord:
    """Map a database row to its API record, keeping the column name authoritative."""
    workspace = PatchWorkspace.model_validate(row.document).model_copy(update={"name": row.name})
    return WorkspaceRecord(
        id=row.workspace_id, revision=row.revision, created_at=row.created_at,
        updated_at=row.updated_at, source="database", workspace=workspace,
    )


def summary_from_record(record: WorkspaceRecord) -> WorkspaceSummary:
    """Drop the canvas graph from a record for the workspace rail."""
    return WorkspaceSummary(
        id=record.id, name=record.workspace.name, patch=record.workspace.patch,
        set_number=record.workspace.set_number, revision=record.revision,
        updated_at=record.updated_at, source=record.source,
    )


def atomic_write(path: Path, content: str) -> None:
    """Replace ``path`` atomically so readers never observe a partial export.

    Mirrors ``spec_service``'s editor write: the content is written to a
    sibling temporary file and moved into place with ``os.replace``. Existing
    permissions are preserved; new files get conventional ``0o644``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, path.stat().st_mode if path.exists() else 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def require_database(source: WorkspaceSource) -> None:
    """Keep the database the single place edits happen.

    Raises:
        WorkspaceReadOnlyError: For the checked-in JSON source.
    """
    if source != "database":
        raise WorkspaceReadOnlyError(
            "Checked-in JSON workspaces are read-only. Import it to the database to edit it."
        )


@contextmanager
def unique_name(session: Session, name: str, noun: str = "workspace") -> Iterator[None]:
    """Translate the unique-name constraint into a conflict for writes in the block.

    PostgreSQL can reject a duplicate name at ``UPDATE`` execution or at
    commit, so the guard wraps both. Workspaces and saved groups both use it.

    Args:
        session: Session performing the write.
        name: Name being written, quoted in the conflict message.
        noun: What is being named, such as ``workspace`` or ``group``.

    Raises:
        WorkspaceConflictError: If another row already uses ``name``.
    """
    try:
        yield
    except IntegrityError:
        session.rollback()
        raise WorkspaceConflictError(f"A {noun} named {name!r} already exists.") from None


def group_from_row(row: DevFlowchartGroup) -> GroupRecord:
    """Map a saved-group row to its API record."""
    return GroupRecord(
        id=row.group_id, name=row.name, set_number=row.set_number,
        created_at=row.created_at, updated_at=row.updated_at,
        fragment=FlowchartFragment.model_validate(row.fragment),
    )
