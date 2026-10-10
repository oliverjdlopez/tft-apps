"""Typed assistant workspace lifecycle and optional experiment bridge routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from services import spec_service
from services.assistant_workspace import bridge, trials
from services.assistant_workspace.models import ExperimentRequest, ImportRequest, RestoreRequest, RevisionRequest, SaveRequest, TrialRequest, WorkspaceState, RunReceipt, ValidationResult
from services.assistant_workspace.workspace import ConflictError

router = APIRouter(prefix='/api/specs', tags=['specs'])


class SpecDocumentBody(BaseModel):
    """Legacy request shape retained to return an explicit migration error."""
    model_config = ConfigDict(extra='forbid')
    content: str = Field(max_length=1_000_000)
    revision: str = Field(min_length=64, max_length=64)


class RefreshRequest(BaseModel):
    """Expected complete source and active revisions for an explicit refresh."""
    model_config = ConfigDict(extra='forbid')
    expected_active: str = Field(min_length=64, max_length=64)
    expected_source: str = Field(min_length=64, max_length=64)


def invoke(operation, *args, **kwargs):
    """Translate domain failures while retaining draft and repository contents."""
    try:
        return operation(*args, **kwargs)
    except KeyError:
        raise HTTPException(404, 'Assistant, revision, or receipt not found') from None
    except ConflictError as exc:
        raise HTTPException(409, str(exc)) from None
    except trials.CapacityError as exc:
        raise HTTPException(429, str(exc)) from None
    except bridge.UnavailableError as exc:
        raise HTTPException(503, str(exc)) from None
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from None


@router.get('')
def spec_workspace() -> dict:
    """List available assistants without hosted service dependencies."""
    return invoke(spec_service.workspace)


@router.get('/documents/{document_id}')
def spec_document(document_id: str) -> dict:
    """Read an existing source document through its opaque identifier."""
    return invoke(spec_service.read_document, document_id)


@router.put('/documents/{document_id}')
def update_spec_document(document_id: str, body: SpecDocumentBody) -> dict:
    """Explicitly retire source writes instead of silently changing semantics."""
    raise HTTPException(410, 'Direct document writes are retired. Save an assistant draft and Apply it through /api/specs/assistants/{name}.')


@router.get('/assistants/{name}', response_model=WorkspaceState)
def assistant_state(name: str) -> dict:
    """Read active/draft instructions, identities, validation, diffs, and history."""
    return invoke(spec_service.workspace_service().state, name)


@router.post('/assistants/{name}/draft', response_model=WorkspaceState)
def save_draft(name: str, body: SaveRequest) -> dict:
    """Save invalid or valid immutable draft files without changing runtime."""
    return invoke(spec_service.workspace_service().save, name, **body.model_dump())


@router.post('/assistants/{name}/validate', response_model=ValidationResult)
def validate_draft(name: str, body: RevisionRequest) -> dict:
    """Revalidate a saved draft against the captured active registry."""
    service = spec_service.workspace_service()
    active, head, _ = invoke(service.check, name, **body.model_dump())
    if head is None:
        raise HTTPException(400, 'Save a draft before validation')
    return invoke(service.validate, name, head['files'], active)


@router.post('/assistants/{name}/apply', response_model=WorkspaceState)
def apply_draft(name: str, body: RevisionRequest) -> dict:
    """Apply validated files through the recoverable checkout transaction."""
    return invoke(spec_service.workspace_service().apply, name, **body.model_dump())


@router.post('/assistants/{name}/discard', response_model=WorkspaceState)
def discard_draft(name: str, body: RevisionRequest) -> dict:
    """Close the editable draft while preserving all history and results."""
    return invoke(spec_service.workspace_service().discard, name, **body.model_dump())


@router.get('/assistants/{name}/history')
def draft_history(name: str) -> dict:
    """Read saved revisions and apply/discard history."""
    service = spec_service.workspace_service()
    invoke(service.active().get_spec, name)
    return service.store.history(name)


@router.post('/assistants/{name}/restore', response_model=WorkspaceState)
def restore_draft(name: str, body: RestoreRequest) -> dict:
    """Restore an earlier immutable revision into a new editable head."""
    return invoke(spec_service.workspace_service().restore, name, **body.model_dump())


@router.post('/refresh')
def refresh_active(body: RefreshRequest) -> dict:
    """Install current repository definitions after whole-graph validation."""
    return invoke(spec_service.workspace_service().refresh, **body.model_dump())


@router.post('/assistants/{name}/trials', status_code=202, response_model=RunReceipt)
def run_trial(name: str, body: TrialRequest) -> dict:
    """Start a bounded trial whose lifetime is independent of the browser."""
    return invoke(trials.start, spec_service.workspace_service(), name, **body.model_dump())


@router.get('/runs/{identity}', response_model=RunReceipt)
def run_status(identity: str) -> dict:
    """Read a trial result or reconcile an experiment's score state."""
    return invoke(bridge.status, spec_service.workspace_service(), identity)


@router.get('/assistants/{name}/datasets')
def experiment_datasets(name: str) -> dict:
    """List eligible registered live datasets or explain service unavailability."""
    return invoke(bridge.datasets, spec_service.workspace_service(), name)


@router.post('/assistants/{name}/experiments', status_code=202, response_model=RunReceipt)
def run_experiment(name: str, body: ExperimentRequest) -> dict:
    """Submit an Active/Draft comparison with a persistent idempotency key."""
    return invoke(bridge.submit, spec_service.workspace_service(), name, **body.model_dump())


@router.get('/assistants/{name}/prompts')
def import_prompts(name: str) -> dict:
    """List owned prompt versions available for import."""
    return invoke(bridge.request, spec_service.workspace_service(), 'GET', '/workspace/prompts/' + name)


@router.post('/assistants/{name}/import', response_model=WorkspaceState)
def import_draft(name: str, body: ImportRequest) -> dict:
    """Create a local draft from an owned concrete hosted prompt version."""
    return invoke(bridge.import_prompt, spec_service.workspace_service(), name, **body.model_dump())
