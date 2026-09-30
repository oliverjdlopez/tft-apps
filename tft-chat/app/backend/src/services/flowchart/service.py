"""Create, save, export, and import player-authored patch gameplan workspaces.

The service also keeps the Flowchart library: named groups of elements saved
from any workspace's canvas and inserted as copies into any other. Groups live
only in the ``chat_tft_dev_flowchart_groups`` table.

The PostgreSQL ``chat_tft_dev_workspaces`` table is the editable source of
truth. Checked-in ``gameplans/<slug>.json`` documents are a read-only second
source: they can be listed, opened, and imported into the database, and any
database workspace can be exported to that format. This is a private player
tool; it never reads match data, projections, or model-facing tools.
"""

from uuid import uuid4

from sqlalchemy import select, update

from common.paths import find_repo_root
from db.models import DevFlowchartGroup, DevWorkspace
from db.session import open_db
from .models import (
    GroupCreateRequest,
    GroupList,
    GroupRecord,
    PatchWorkspace,
    WorkspaceConflictError,
    WorkspaceExport,
    WorkspaceList,
    WorkspaceRecord,
    WorkspaceSource,
)
from .utils import (
    atomic_write,
    group_from_row,
    json_workspace_path,
    json_workspace_paths,
    record_from_file,
    record_from_row,
    require_database,
    slugify,
    summary_from_record,
    unique_name,
)

GAMEPLANS_DIR = find_repo_root() / "gameplans"


def list_workspaces(source: WorkspaceSource) -> WorkspaceList:
    """List workspace summaries from one source, newest database edits first.

    Args:
        source: ``database`` rows or checked-in ``json`` documents.

    Returns:
        Summaries for the Flowchart rail. Invalid JSON files are skipped.
    """
    if source == "json":
        records = []
        for path in json_workspace_paths(GAMEPLANS_DIR):
            try:
                records.append(record_from_file(path))
            except (OSError, ValueError):
                # One hand-edited broken file must not hide every other gameplan.
                continue
    else:
        with open_db() as session:
            rows = session.scalars(select(DevWorkspace).order_by(DevWorkspace.updated_at.desc()))
            records = [record_from_row(row) for row in rows]
    return WorkspaceList(source=source, workspaces=[summary_from_record(r) for r in records])


def get_workspace(workspace_id: str, source: WorkspaceSource) -> WorkspaceRecord:
    """Open one workspace document.

    Raises:
        LookupError: If the workspace does not exist in ``source``.
        ValueError: If a checked-in JSON document fails validation.
    """
    if source == "json":
        path = json_workspace_path(GAMEPLANS_DIR, workspace_id)
        if not path.is_file():
            raise LookupError("workspace not found")
        return record_from_file(path)
    with open_db() as session:
        row = session.get(DevWorkspace, workspace_id)
        if row is None:
            raise LookupError("workspace not found")
        return record_from_row(row)


def create_workspace(workspace: PatchWorkspace, source: WorkspaceSource) -> WorkspaceRecord:
    """Insert a named workspace document at revision 1.

    Raises:
        WorkspaceReadOnlyError: For the checked-in JSON source.
        WorkspaceConflictError: If the name is already in use.
    """
    require_database(source)
    row = DevWorkspace(
        workspace_id=str(uuid4()), name=workspace.name, revision=1,
        document=workspace.model_dump(mode="json"),
    )
    with open_db() as session, unique_name(session, workspace.name):
        session.add(row)
        session.commit()
        return record_from_row(row)


def save_workspace(
    workspace_id: str, revision: int, workspace: PatchWorkspace, source: WorkspaceSource
) -> WorkspaceRecord:
    """Replace a workspace document using optimistic concurrency.

    The update only matches the row while its stored revision equals
    ``revision``, so two editors cannot silently overwrite each other; the
    loser receives a conflict and reloads.

    Raises:
        LookupError: If the workspace does not exist.
        WorkspaceConflictError: On a stale revision or a duplicate name.
        WorkspaceReadOnlyError: For the checked-in JSON source.
    """
    require_database(source)
    with open_db() as session, unique_name(session, workspace.name):
        result = session.execute(
            update(DevWorkspace)
            .where(DevWorkspace.workspace_id == workspace_id, DevWorkspace.revision == revision)
            .values(
                name=workspace.name, revision=revision + 1,
                document=workspace.model_dump(mode="json"),
            )
        )
        if result.rowcount != 1:
            session.rollback()
            if session.get(DevWorkspace, workspace_id) is None:
                raise LookupError("workspace not found")
            raise WorkspaceConflictError(
                "This workspace changed after it was opened. Reload it before saving."
            )
        session.commit()
        return record_from_row(session.get(DevWorkspace, workspace_id, populate_existing=True))


def rename_workspace(
    workspace_id: str, revision: int, name: str, source: WorkspaceSource
) -> WorkspaceRecord:
    """Rename a workspace, keeping the column and embedded document name aligned."""
    require_database(source)
    current = get_workspace(workspace_id, source)
    renamed = current.workspace.model_copy(update={"name": name})
    return save_workspace(workspace_id, revision, renamed, source)


def delete_workspace(workspace_id: str, source: WorkspaceSource) -> None:
    """Permanently delete a database workspace; exported JSON files are kept.

    Raises:
        LookupError: If the workspace does not exist.
        WorkspaceReadOnlyError: For the checked-in JSON source.
    """
    require_database(source)
    with open_db() as session:
        row = session.get(DevWorkspace, workspace_id)
        if row is None:
            raise LookupError("workspace not found")
        session.delete(row)
        session.commit()


def export_workspace(workspace_id: str, source: WorkspaceSource) -> WorkspaceExport:
    """Write a workspace to ``gameplans/<slug>.json`` for check-in.

    The file holds exactly the portable ``PatchWorkspace`` document, and the
    slug is derived from the workspace name, so re-exporting overwrites the
    same file.
    """
    workspace = get_workspace(workspace_id, source).workspace
    path = json_workspace_path(GAMEPLANS_DIR, slugify(workspace.name))
    atomic_write(path, workspace.model_dump_json(indent=2) + "\n")
    return WorkspaceExport(path=path.relative_to(GAMEPLANS_DIR.parent).as_posix(), workspace=workspace)


def import_workspace(workspace: PatchWorkspace) -> WorkspaceRecord:
    """Copy a portable workspace document, usually a checked-in JSON one, into the database.

    Raises:
        WorkspaceConflictError: If a database workspace already uses the name.
    """
    return create_workspace(workspace, "database")


def list_groups() -> GroupList:
    """List the Flowchart library's saved groups, most recently updated first."""
    with open_db() as session:
        rows = session.scalars(select(DevFlowchartGroup).order_by(DevFlowchartGroup.updated_at.desc()))
        return GroupList(groups=[group_from_row(row) for row in rows])


def create_group(request: GroupCreateRequest) -> GroupRecord:
    """Save a named group of canvas elements to the library.

    Raises:
        WorkspaceConflictError: If a group already uses the name.
    """
    row = DevFlowchartGroup(
        group_id=str(uuid4()), name=request.name, set_number=request.set_number,
        fragment=request.fragment.model_dump(mode="json"),
    )
    with open_db() as session, unique_name(session, request.name, "group"):
        session.add(row)
        session.commit()
        return group_from_row(row)


def rename_group(group_id: str, name: str) -> GroupRecord:
    """Rename a saved group.

    Raises:
        LookupError: If the group does not exist.
        WorkspaceConflictError: If another group already uses the name.
    """
    with open_db() as session, unique_name(session, name, "group"):
        row = session.get(DevFlowchartGroup, group_id)
        if row is None:
            raise LookupError("group not found")
        row.name = name
        session.commit()
        return group_from_row(row)


def delete_group(group_id: str) -> None:
    """Delete a saved group; elements already inserted into workspaces are kept.

    Raises:
        LookupError: If the group does not exist.
    """
    with open_db() as session:
        row = session.get(DevFlowchartGroup, group_id)
        if row is None:
            raise LookupError("group not found")
        session.delete(row)
        session.commit()
