"""HTTP contracts for flowchart workspaces over both database and JSON sources."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.routes import flowchart
from db.models import DevFlowchartGroup, DevWorkspace
from services.flowchart import service


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Route the service to a private SQLite table and a temporary ``gameplans/``.

    The workspace table uses portable JSON columns, so a disposable in-memory
    store exercises the real revision and unique-name behavior without touching
    any application database.
    """
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    DevWorkspace.__table__.create(engine)
    DevFlowchartGroup.__table__.create(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(service, "open_db", lambda: sessions())
    monkeypatch.setattr(service, "GAMEPLANS_DIR", tmp_path / "gameplans")
    monkeypatch.setattr(
        flowchart, "load_config",
        lambda: SimpleNamespace(chat=SimpleNamespace(flowchart_source="database")),
    )
    app = FastAPI()
    app.include_router(flowchart.router)
    yield TestClient(app)
    engine.dispose()


ELEMENTS = [
    {"id": "open", "kind": "plan", "position": {"x": 0, "y": 0}, "title": "Opener",
     "stage_hint": "2-1", "entities": [{"category": "unit", "api_name": "TFT17_Ashe"}]},
    {"id": "comp", "kind": "plan", "position": {"x": 300, "y": 0}, "title": "Reroll"},
    {"id": "why", "kind": "note", "position": {"x": 0, "y": 200}, "text": "If contested"},
]


def document(name="Opener plan", **flowchart_overrides):
    """Build a small valid workspace document with a plan, note, and two links."""
    graph = {
        "elements": ELEMENTS,
        "connections": [
            {"id": "t1", "source": "open", "target": "comp", "kind": "transition",
             "condition": "Hit 3-star by 3-2"},
            {"id": "a1", "source": "why", "target": "open", "kind": "annotation"},
        ],
        "viewport": {"x": 10, "y": 20, "zoom": 0.8},
        **flowchart_overrides,
    }
    return {"schema_version": "flowchart.v1", "name": name, "patch": "17.1",
            "set_number": 17, "gameplan": {"flowchart": graph}}


def create(client, name="Opener plan"):
    """Create an empty database workspace and return its record."""
    response = client.post("/api/flowchart/workspaces", json={"name": name, "patch": "17.1", "set_number": 17})
    assert response.status_code == 201
    return response.json()


def test_database_crud_and_optimistic_revisions(client):
    """Saves advance revisions, stale saves conflict, and deletes remove the row."""
    record = create(client)
    assert record["source"] == "database" and record["revision"] == 1
    assert record["workspace"]["gameplan"]["flowchart"]["elements"] == []

    saved = client.put(f"/api/flowchart/workspaces/{record['id']}",
                       json={"revision": 1, "workspace": document()})
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert saved.json()["workspace"]["gameplan"]["flowchart"]["viewport"]["zoom"] == 0.8

    stale = client.put(f"/api/flowchart/workspaces/{record['id']}",
                       json={"revision": 1, "workspace": document()})
    assert stale.status_code == 409

    renamed = client.patch(f"/api/flowchart/workspaces/{record['id']}", json={"revision": 2, "name": "Late game"})
    assert renamed.status_code == 200
    assert renamed.json()["workspace"]["name"] == "Late game" and renamed.json()["revision"] == 3
    listed = client.get("/api/flowchart/workspaces").json()
    assert listed["source"] == "database"
    assert [w["name"] for w in listed["workspaces"]] == ["Late game"]

    assert client.delete(f"/api/flowchart/workspaces/{record['id']}").status_code == 204
    assert client.get(f"/api/flowchart/workspaces/{record['id']}").status_code == 404
    assert client.put("/api/flowchart/workspaces/missing",
                      json={"revision": 1, "workspace": document()}).status_code == 404


def test_duplicate_names_conflict(client):
    """Workspace names are unique for creates, saves, and renames."""
    first = create(client, "A")
    create(client, "B")
    assert client.post("/api/flowchart/workspaces", json={"name": "A"}).status_code == 409
    assert client.patch(f"/api/flowchart/workspaces/{first['id']}", json={"revision": 1, "name": "B"}).status_code == 409
    # The failed rename must leave the stored revision untouched.
    assert client.get(f"/api/flowchart/workspaces/{first['id']}").json()["revision"] == 1


@pytest.mark.parametrize("overrides, message", [
    ({"connections": [{"id": "t", "source": "open", "target": "gone"}]}, "missing element"),
    ({"elements": [{"id": "x", "kind": "note", "position": {"x": 0, "y": 0}}] * 2, "connections": []},
     "element ids must be unique"),
    ({"connections": [{"id": "t", "source": "open", "target": "comp"}] * 2}, "connection ids must be unique"),
    ({"connections": [{"id": "t", "source": "open", "target": "comp", "kind": "annotation"}]}, "must attach a note"),
    ({"connections": [{"id": "t", "source": "why", "target": "open"}]}, "use an annotation"),
    ({"elements": [*ELEMENTS, {"id": "go", "kind": "start", "position": {"x": 0, "y": 0}}],
      "connections": [{"id": "t", "source": "open", "target": "go"}]}, "cannot enter a start"),
    ({"elements": [*ELEMENTS, {"id": "done", "kind": "end", "position": {"x": 0, "y": 0}}],
      "connections": [{"id": "t", "source": "done", "target": "open"}]}, "cannot leave an end"),
    ({"elements": [{"id": "q", "kind": "decision", "position": {"x": 0, "y": 0},
                    "entities": [{"category": "unit", "api_name": "TFT17_Ashe"}]}], "connections": []},
     "decision elements cannot hold entities"),
    ({"connections": [{"id": "t", "source": "open", "target": "comp", "source_handle": "middle"}]}, "source_handle"),
])
def test_invalid_graphs_are_rejected(client, overrides, message):
    """Dangling links, duplicate ids, and note-less annotations fail validation."""
    record = create(client)
    response = client.put(f"/api/flowchart/workspaces/{record['id']}",
                          json={"revision": 1, "workspace": document(**overrides)})
    assert response.status_code == 422
    assert message in json.dumps(response.json())


def test_activity_graph_round_trips(client):
    """Decisions, actions, forks, and start/end nodes save with guards, notes, and handles."""
    record = create(client)
    at = {"x": 0, "y": 0}
    elements = [
        {"id": "go", "kind": "start", "position": at},
        {"id": "roll", "kind": "action", "position": at, "title": "Roll at 3-1",
         "entities": [{"category": "item", "api_name": "TFT_Item_InfinityEdge"}]},
        {"id": "hit", "kind": "decision", "position": at, "title": "Hit 3-star?"},
        {"id": "split", "kind": "fork", "position": at, "size": {"width": 14, "height": 120}},
        {"id": "comp", "kind": "plan", "position": at, "title": "Reroll"},
        {"id": "econ", "kind": "action", "position": at, "title": "Save to 50"},
        {"id": "done", "kind": "end", "position": at},
        {"id": "why", "kind": "note", "position": at, "text": "Contested lobbies"},
    ]
    connections = [
        {"id": "t1", "source": "go", "target": "roll"},
        {"id": "t2", "source": "roll", "target": "hit"},
        {"id": "t3", "source": "hit", "target": "comp", "condition": "yes", "source_handle": "right",
         "notes": "Slam carry items immediately"},
        {"id": "t4", "source": "hit", "target": "split", "condition": "else", "source_handle": "bottom"},
        {"id": "t5", "source": "split", "target": "econ"},
        {"id": "t6", "source": "split", "target": "comp"},
        {"id": "t7", "source": "comp", "target": "done"},
        {"id": "a1", "source": "why", "target": "hit", "kind": "annotation", "target_handle": "top"},
    ]
    workspace = document(elements=elements, connections=connections)
    saved = client.put(f"/api/flowchart/workspaces/{record['id']}", json={"revision": 1, "workspace": workspace})
    assert saved.status_code == 200
    graph = saved.json()["workspace"]["gameplan"]["flowchart"]
    assert [element["kind"] for element in graph["elements"]] == [element["kind"] for element in elements]
    branch = next(connection for connection in graph["connections"] if connection["id"] == "t3")
    assert branch["source_handle"] == "right" and branch["target_handle"] is None
    assert branch["notes"] == "Slam carry items immediately"


def test_unknown_fields_and_bad_entities_are_rejected(client):
    """Documents forbid extra fields and malformed entity nodes."""
    record = create(client)
    extra = {**document(), "owner": "someone"}
    assert client.put(f"/api/flowchart/workspaces/{record['id']}",
                      json={"revision": 1, "workspace": extra}).status_code == 422
    bad_entity = document(elements=[{"id": "e", "kind": "entity", "position": {"x": 0, "y": 0}}], connections=[])
    assert client.put(f"/api/flowchart/workspaces/{record['id']}",
                      json={"revision": 1, "workspace": bad_entity}).status_code == 422


def test_export_then_read_only_json_source_and_import(client, tmp_path):
    """Exports write the portable document; the JSON source is read-only but importable."""
    record = create(client, "Ashe Reroll!")
    client.put(f"/api/flowchart/workspaces/{record['id']}",
               json={"revision": 1, "workspace": document("Ashe Reroll!")})

    exported = client.post(f"/api/flowchart/workspaces/{record['id']}/export")
    assert exported.status_code == 200
    assert exported.json()["path"] == "gameplans/ashe-reroll.json"
    written = json.loads((tmp_path / "gameplans" / "ashe-reroll.json").read_text())
    assert written == exported.json()["workspace"]
    assert written["schema_version"] == "flowchart.v2" and written["name"] == "Ashe Reroll!"
    assert written["gameplan"]["flowchart"]["connections"][0]["condition"] == "Hit 3-star by 3-2"

    listed = client.get("/api/flowchart/workspaces", params={"source": "json"}).json()
    assert [(w["id"], w["source"]) for w in listed["workspaces"]] == [("ashe-reroll", "json")]
    opened = client.get("/api/flowchart/workspaces/ashe-reroll", params={"source": "json"})
    assert opened.status_code == 200 and opened.json()["workspace"]["name"] == "Ashe Reroll!"

    read_only = client.put("/api/flowchart/workspaces/ashe-reroll", params={"source": "json"},
                           json={"revision": 1, "workspace": document()})
    assert read_only.status_code == 400 and "read-only" in read_only.json()["detail"]
    assert client.delete("/api/flowchart/workspaces/ashe-reroll", params={"source": "json"}).status_code == 400
    assert client.get("/api/flowchart/workspaces/..%2Fsecret", params={"source": "json"}).status_code == 404

    duplicate = client.post("/api/flowchart/workspaces/import", json={"workspace": opened.json()["workspace"]})
    assert duplicate.status_code == 409
    client.delete(f"/api/flowchart/workspaces/{record['id']}")
    imported = client.post("/api/flowchart/workspaces/import", json={"workspace": opened.json()["workspace"]})
    assert imported.status_code == 201 and imported.json()["source"] == "database"


def test_json_source_skips_invalid_files_and_uses_configured_default(client, tmp_path, monkeypatch):
    """A broken checked-in file is hidden, and the INI default selects the source."""
    folder = tmp_path / "gameplans"
    folder.mkdir()
    (folder / "good.json").write_text(json.dumps(document("Good")))
    (folder / "broken.json").write_text("{not json")
    (folder / "Bad Name.json").write_text(json.dumps(document("Ignored")))
    monkeypatch.setattr(
        flowchart, "load_config",
        lambda: SimpleNamespace(chat=SimpleNamespace(flowchart_source="json")),
    )
    listed = client.get("/api/flowchart/workspaces").json()
    assert listed["source"] == "json"
    assert [w["name"] for w in listed["workspaces"]] == ["Good"]
    assert client.get("/api/flowchart/workspaces/broken").status_code == 400
    assert client.get("/api/flowchart/workspaces", params={"source": "other"}).status_code == 422


def test_saved_groups_create_list_rename_and_delete(client):
    """The library stores validated fragments by unique name, independent of workspaces."""
    fragment = {
        "elements": [
            {"id": "s", "kind": "plan", "position": {"x": 0, "y": 0}, "title": "Ashe reroll",
             "entities": [{"category": "unit", "api_name": "TFT17_Ashe"}]},
            {"id": "a", "kind": "action", "position": {"x": 0, "y": 160}, "title": "Roll at 3-1"},
        ],
        "connections": [{"id": "t", "source": "s", "target": "a", "condition": "hit 2-star"}],
    }
    created = client.post("/api/flowchart/groups", json={"name": "Reroll core", "set_number": 17, "fragment": fragment})
    assert created.status_code == 201
    group = created.json()
    assert group["fragment"]["connections"][0]["condition"] == "hit 2-star"
    assert group["set_number"] == 17

    duplicate = client.post("/api/flowchart/groups", json={"name": "Reroll core", "fragment": fragment})
    assert duplicate.status_code == 409 and "group named" in duplicate.json()["detail"]
    empty = client.post("/api/flowchart/groups", json={"name": "Empty", "fragment": {"elements": []}})
    assert empty.status_code == 422
    dangling = {"elements": fragment["elements"][:1], "connections": fragment["connections"]}
    assert client.post("/api/flowchart/groups", json={"name": "Bad", "fragment": dangling}).status_code == 422

    renamed = client.patch(f"/api/flowchart/groups/{group['id']}", json={"name": "Reroll opener"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Reroll opener"
    assert [g["name"] for g in client.get("/api/flowchart/groups").json()["groups"]] == ["Reroll opener"]

    assert client.delete(f"/api/flowchart/groups/{group['id']}").status_code == 204
    assert client.delete(f"/api/flowchart/groups/{group['id']}").status_code == 404
    assert client.get("/api/flowchart/groups").json() == {"groups": []}


def nested_document(name="Nested"):
    """Build a v2 graph covering containment, locks, and manual route metadata."""
    value = document(name)
    value["schema_version"] = "flowchart.v2"
    value["gameplan"]["flowchart"]["elements"] = [
        {"id": "outer", "kind": "group", "title": "Branch", "tint": "#dbeafe",
         "position": {"x": 100, "y": 100}, "size": {"width": 700, "height": 600}},
        {"id": "inner", "kind": "group", "parent_id": "outer",
         "position": {"x": 24, "y": 48}, "size": {"width": 500, "height": 400}},
        {"id": "open", "kind": "action", "parent_id": "inner", "locked": True,
         "position": {"x": 24, "y": 48}, "title": "Roll"},
        {"id": "comp", "kind": "plan", "parent_id": "outer",
         "position": {"x": 400, "y": 450}, "title": "Pivot"},
    ]
    value["gameplan"]["flowchart"]["connections"] = [
        {"id": "t", "source": "open", "target": "comp", "condition": "hit", "notes": "preserve",
         "waypoints": [{"x": 700, "y": 200}, {"x": 700, "y": 500}], "label_offset": {"x": 15, "y": -20}},
    ]
    return value


def test_v2_nested_save_import_export_and_library(client, tmp_path):
    """V2 metadata survives every portable/storage boundary with unchanged revision checks."""
    imported = client.post("/api/flowchart/workspaces/import", json={"workspace": nested_document()})
    assert imported.status_code == 201
    record = imported.json()
    assert record["workspace"]["schema_version"] == "flowchart.v2"
    exported = client.post(f"/api/flowchart/workspaces/{record['id']}/export")
    assert exported.json()["workspace"] == record["workspace"]
    assert json.loads((tmp_path / "gameplans" / "nested.json").read_text()) == record["workspace"]
    saved = client.put(f"/api/flowchart/workspaces/{record['id']}",
                       json={"revision": 1, "workspace": record["workspace"]})
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert client.put(f"/api/flowchart/workspaces/{record['id']}",
                      json={"revision": 1, "workspace": record["workspace"]}).status_code == 409
    graph = record["workspace"]["gameplan"]["flowchart"]
    fragment = {"elements": graph["elements"], "connections": graph["connections"]}
    group = client.post("/api/flowchart/groups", json={"name": "Nested branch", "fragment": fragment})
    assert group.status_code == 201
    assert client.get("/api/flowchart/groups").json()["groups"][0]["fragment"] == fragment


def test_open_legacy_sources_never_rewrites_or_increments_revision(client, tmp_path):
    """Opening v1 upgrades only the response, preserving source JSON and database contents."""
    original = document("Legacy")
    directory = tmp_path / "gameplans"
    directory.mkdir()
    path = directory / "legacy.json"
    content = json.dumps(original)
    path.write_text(content)
    record = client.get("/api/flowchart/workspaces/legacy?source=json").json()
    assert record["workspace"]["schema_version"] == "flowchart.v2"
    assert path.read_text() == content
    with service.open_db() as session:
        session.add(DevWorkspace(workspace_id="legacy", name="Legacy", revision=9, document=original))
        session.commit()
    loaded = client.get("/api/flowchart/workspaces/legacy").json()
    assert loaded["revision"] == 9 and loaded["workspace"]["schema_version"] == "flowchart.v2"
    with service.open_db() as session:
        row = session.get(DevWorkspace, "legacy")
        assert row.revision == 9 and row.document == original


@pytest.mark.parametrize("invalid", ["missing", "ancestor_missing", "non_group", "self", "cycle", "infinite", "size", "waypoints", "label", "tint", "container_link"])
def test_v2_invalid_containment_and_routing_are_rejected(client, invalid):
    """Reject malformed nested graphs and bounded metadata at the HTTP request boundary."""
    value = nested_document()
    graph = value["gameplan"]["flowchart"]
    outer, inner, child, _ = graph["elements"]
    edge = graph["connections"][0]
    if invalid == "missing": child["parent_id"] = "missing"
    if invalid == "ancestor_missing":
        inner["parent_id"] = "missing"
        graph["elements"] = [child, outer, inner, graph["elements"][3]]
    if invalid == "non_group": inner["parent_id"] = "comp"
    if invalid == "self": outer["parent_id"] = "outer"
    if invalid == "cycle": outer["parent_id"] = "inner"
    if invalid == "infinite": child["position"]["x"] = 1_000_001
    if invalid == "size": outer["size"]["width"] = 4001
    if invalid == "waypoints": edge["waypoints"] = [{"x": 0, "y": 0}] * 65
    if invalid == "label": edge["label_offset"]["y"] = 1_000_001
    if invalid == "tint": outer["tint"] = "url(external)"
    if invalid == "container_link": edge["source"] = "outer"
    assert client.post("/api/flowchart/workspaces/import", json={"workspace": value}).status_code == 422


def test_nonfinite_model_geometry():
    """Pydantic rejects NaN and infinity even outside the HTTP JSON decoder."""
    from pydantic import ValidationError
    from services.flowchart.models import PatchWorkspace

    for coordinate in (float("nan"), float("inf"), float("-inf")):
        value = nested_document()
        value["gameplan"]["flowchart"]["elements"][0]["position"]["x"] = coordinate
        with pytest.raises(ValidationError):
            PatchWorkspace.model_validate(value)
