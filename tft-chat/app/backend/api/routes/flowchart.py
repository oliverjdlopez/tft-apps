"""Flowchart workspace HTTP routes for the desktop Flowchart tab.

Handlers are synchronous so FastAPI runs database and file work in its thread
pool instead of on the event loop. Every workspace route accepts ``?source=``
to override the configured ``[chat] flowchart_source`` default; the saved-group
library routes always use the database.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from core.config import load_config
from services.flowchart import service
from services.flowchart.models import (
    GroupCreateRequest,
    GroupList,
    GroupRecord,
    GroupRenameRequest,
    PatchWorkspace,
    WorkspaceConflictError,
    WorkspaceCreateRequest,
    WorkspaceExport,
    WorkspaceImportRequest,
    WorkspaceList,
    WorkspaceReadOnlyError,
    WorkspaceRecord,
    WorkspaceRenameRequest,
    WorkspaceSaveRequest,
    WorkspaceSource,
)

router = APIRouter(prefix="/api/flowchart", tags=["flowchart"])


def effective_source(source: WorkspaceSource | None) -> WorkspaceSource:
    """Apply the configured default when a request does not choose a source."""
    return source or load_config().chat.flowchart_source


def run_workspace_call(call, *args):
    """Invoke a service operation, mapping domain errors onto HTTP status codes.

    Missing workspaces or groups become 404, stale revisions and duplicate names 409, and
    read-only or invalid documents 400.
    """
    try:
        return call(*args)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    except WorkspaceConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except (WorkspaceReadOnlyError, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from None


@router.get("/workspaces", response_model=WorkspaceList)
def list_workspaces(source: WorkspaceSource | None = None) -> WorkspaceList:
    """List workspace summaries from the chosen source."""
    return run_workspace_call(service.list_workspaces, effective_source(source))


@router.post("/workspaces", response_model=WorkspaceRecord, status_code=201)
def create_workspace(
    body: WorkspaceCreateRequest, source: WorkspaceSource | None = None
) -> WorkspaceRecord:
    """Create an empty named workspace in the database."""
    workspace = PatchWorkspace(name=body.name, patch=body.patch, set_number=body.set_number)
    return run_workspace_call(service.create_workspace, workspace, effective_source(source))


@router.post("/workspaces/import", response_model=WorkspaceRecord, status_code=201)
def import_workspace(body: WorkspaceImportRequest) -> WorkspaceRecord:
    """Copy a portable workspace document into the editable database source."""
    return run_workspace_call(service.import_workspace, body.workspace)


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceRecord)
def get_workspace(workspace_id: str, source: WorkspaceSource | None = None) -> WorkspaceRecord:
    """Open one workspace document."""
    return run_workspace_call(service.get_workspace, workspace_id, effective_source(source))


@router.put("/workspaces/{workspace_id}", response_model=WorkspaceRecord)
def save_workspace(
    workspace_id: str, body: WorkspaceSaveRequest, source: WorkspaceSource | None = None
) -> WorkspaceRecord:
    """Replace a workspace document when the client's revision is current."""
    return run_workspace_call(
        service.save_workspace, workspace_id, body.revision, body.workspace, effective_source(source)
    )


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceRecord)
def rename_workspace(
    workspace_id: str, body: WorkspaceRenameRequest, source: WorkspaceSource | None = None
) -> WorkspaceRecord:
    """Rename a workspace when the client's revision is current."""
    return run_workspace_call(
        service.rename_workspace, workspace_id, body.revision, body.name, effective_source(source)
    )


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, source: WorkspaceSource | None = None) -> Response:
    """Permanently delete a database workspace."""
    run_workspace_call(service.delete_workspace, workspace_id, effective_source(source))
    return Response(status_code=204)


@router.post("/workspaces/{workspace_id}/export", response_model=WorkspaceExport)
def export_workspace(workspace_id: str, source: WorkspaceSource | None = None) -> WorkspaceExport:
    """Write a workspace to ``gameplans/<slug>.json`` and return the document."""
    return run_workspace_call(service.export_workspace, workspace_id, effective_source(source))


@router.get("/groups", response_model=GroupList)
def list_groups() -> GroupList:
    """List the saved groups in the Flowchart library."""
    return run_workspace_call(service.list_groups)


@router.post("/groups", response_model=GroupRecord, status_code=201)
def create_group(body: GroupCreateRequest) -> GroupRecord:
    """Save a selection of canvas elements as a named group."""
    return run_workspace_call(service.create_group, body)


@router.patch("/groups/{group_id}", response_model=GroupRecord)
def rename_group(group_id: str, body: GroupRenameRequest) -> GroupRecord:
    """Rename a saved group."""
    return run_workspace_call(service.rename_group, group_id, body.name)


@router.delete("/groups/{group_id}", status_code=204)
def delete_group(group_id: str) -> Response:
    """Delete a saved group from the library."""
    run_workspace_call(service.delete_group, group_id)
    return Response(status_code=204)
