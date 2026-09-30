"""Flowchart workspace CRUD against the isolated RDS_TEST PostgreSQL target."""

import pytest

from db.session import open_db
from services.flowchart import service
from services.flowchart.models import (
    FlowchartFragment,
    GroupCreateRequest,
    PatchWorkspace,
    WorkspaceConflictError,
)


@pytest.fixture
def isolated_store(clean_db, monkeypatch):
    """Route workspace reads and writes only to the repository's test database."""
    monkeypatch.setattr(service, "open_db", lambda: open_db(purpose="test"))
    yield


def test_workspace_round_trip_revisions_and_names(isolated_store):
    """PostgreSQL enforces revision checks and unique names for the runtime table."""
    record = service.create_workspace(PatchWorkspace(name="Opener", patch="17.1", set_number=17), "database")
    assert record.revision == 1 and record.created_at is not None

    document = PatchWorkspace.model_validate({
        "name": "Opener",
        "gameplan": {"flowchart": {
            "elements": [{"id": "p", "kind": "plan", "position": {"x": 1, "y": 2},
                          "entities": [{"category": "augment", "api_name": "TFT_Augment_Example"}]}],
            "viewport": {"x": 5, "y": 6, "zoom": 1.5},
        }},
    })
    saved = service.save_workspace(record.id, 1, document, "database")
    assert saved.revision == 2
    assert service.get_workspace(record.id, "database").workspace == document

    with pytest.raises(WorkspaceConflictError):
        service.save_workspace(record.id, 1, document, "database")
    service.create_workspace(PatchWorkspace(name="Other"), "database")
    with pytest.raises(WorkspaceConflictError):
        service.rename_workspace(record.id, 2, "Other", "database")
    assert service.get_workspace(record.id, "database").revision == 2

    assert [w.name for w in service.list_workspaces("database").workspaces] == ["Other", "Opener"]
    service.delete_workspace(record.id, "database")
    with pytest.raises(LookupError):
        service.get_workspace(record.id, "database")


def test_group_library_round_trip_and_unique_names(isolated_store):
    """PostgreSQL stores saved groups and enforces their unique names."""
    fragment = FlowchartFragment.model_validate({
        "elements": [{"id": "a", "kind": "action", "position": {"x": 0, "y": 0}, "title": "Slam items"}],
    })
    group = service.create_group(GroupCreateRequest(name="Slam", set_number=17, fragment=fragment))
    assert service.list_groups().groups[0].fragment == fragment
    with pytest.raises(WorkspaceConflictError):
        service.create_group(GroupCreateRequest(name="Slam", fragment=fragment))
    service.delete_group(group.id)
    assert service.list_groups().groups == []
