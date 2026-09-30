"""Portable flowchart workspace documents and their HTTP request contracts.

A ``PatchWorkspace`` is the single portable document: it is stored in the
``chat_tft_dev_workspaces.document`` column and is exactly what a checked-in
``gameplans/<slug>.json`` export contains. Entities are stored by API name only,
so images are resolved at render time and a patch-bundle change never breaks a
saved document.
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_ELEMENTS = 400
MAX_CONNECTIONS = 800
MAX_ENTITIES_PER_ELEMENT = 40

WorkspaceSource = Literal["database", "json"]
ElementId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]
WorkspaceName = Annotated[str, Field(min_length=1, max_length=120)]
PatchLabel = Annotated[str, Field(min_length=1, max_length=40)]
SetNumber = Annotated[int, Field(ge=1, le=99)]
Coordinate = Annotated[float, Field(ge=-1_000_000, le=1_000_000)]
ElementKind = Literal["plan", "action", "decision", "fork", "start", "end", "entity", "note"]
HandleSide = Literal["top", "right", "bottom", "left"]

# Kinds that may carry entity chips; ``entity`` nodes hold exactly one instead.
CHIP_KINDS = frozenset({"plan", "action"})


class WorkspaceConflictError(ValueError):
    """Raised when a save targets a stale revision or a workspace name already in use."""


class WorkspaceReadOnlyError(ValueError):
    """Raised when a caller tries to edit a checked-in JSON workspace in place."""


class FlowchartModel(BaseModel):
    """Reject unexpected fields at every flowchart document and API boundary."""

    model_config = ConfigDict(extra="forbid")


class EntityRef(FlowchartModel):
    """Reference one draggable unit, item, or augment by its Community Dragon API name.

    Used by state and action chips and standalone entity nodes. Only the API name persists;
    the browser resolves names and images from ``/api/assets/catalog``.
    """

    category: Literal["unit", "item", "augment"]
    api_name: Annotated[str, Field(min_length=1, max_length=120)]


class Position(FlowchartModel):
    """Place an element's top-left corner in React Flow canvas coordinates."""

    x: Coordinate
    y: Coordinate


class Size(FlowchartModel):
    """Record a user-resized element's canvas dimensions."""

    width: Annotated[float, Field(gt=0, le=4000)]
    height: Annotated[float, Field(gt=0, le=4000)]


class Viewport(FlowchartModel):
    """Restore the canvas pan and zoom when a workspace is reopened."""

    x: Coordinate = 0
    y: Coordinate = 0
    zoom: Annotated[float, Field(gt=0, le=10)] = 1


class FlowchartElement(FlowchartModel):
    """Describe one canvas node by its role in the player's decision graph.

    The kinds borrow from UML activity diagrams without enforcing them strictly:

    - ``plan``: a strategic state or line (opener, composition, pivot) with a
      title, optional stage hint, and entity chips.
    - ``action``: something the player does, such as "slam items" or "roll at
      4-1", optionally with the entities it involves.
    - ``decision``: a question whose outgoing transitions carry the guards that
      choose a branch; several incoming transitions make it a merge.
    - ``fork``: a bar that splits one path into parallel ones or joins them.
    - ``start`` / ``end``: where the gameplan begins and where a line finishes.
    - ``entity``: a single dropped icon.
    - ``note``: a situational annotation whose content lives in ``text``.
    """

    id: ElementId
    kind: ElementKind
    position: Position
    size: Size | None = None
    title: Annotated[str, Field(max_length=120)] = ""
    stage_hint: Annotated[str, Field(max_length=40)] | None = None
    entities: Annotated[list[EntityRef], Field(max_length=MAX_ENTITIES_PER_ELEMENT)] = []
    text: Annotated[str, Field(max_length=4000)] = ""

    @model_validator(mode="after")
    def validate_kind_contents(self) -> "FlowchartElement":
        """Keep each node kind's contents consistent with how the canvas renders it."""
        if self.kind == "entity" and len(self.entities) != 1:
            raise ValueError("entity elements hold exactly one entity")
        if self.kind not in CHIP_KINDS | {"entity"} and self.entities:
            raise ValueError(f"{self.kind} elements cannot hold entities")
        return self


class FlowchartConnection(FlowchartModel):
    """Link two elements with a guarded transition or a note annotation.

    A transition's ``condition`` is its guard: the "when/why" label that says
    when the player should take it. ``notes`` hold situational detail drawn
    beside that transition. An annotation attaches a note to the element it
    explains. ``source_handle`` and ``target_handle`` remember which side of a
    multi-handle node (a decision) the link uses; ``None`` means the node's
    only handle.
    """

    id: ElementId
    source: ElementId
    target: ElementId
    kind: Literal["transition", "annotation"] = "transition"
    condition: Annotated[str, Field(max_length=200)] = ""
    notes: Annotated[str, Field(max_length=2000)] = ""
    source_handle: HandleSide | None = None
    target_handle: HandleSide | None = None


class FlowchartFragment(FlowchartModel):
    """Hold canvas elements and the connections between them, validated as one graph.

    A saved group in the Flowchart library is a fragment; ``Flowchart`` extends
    it with the saved viewport, so both share one set of graph rules.
    """

    elements: Annotated[list[FlowchartElement], Field(max_length=MAX_ELEMENTS)] = []
    connections: Annotated[list[FlowchartConnection], Field(max_length=MAX_CONNECTIONS)] = []

    @model_validator(mode="after")
    def validate_graph(self) -> "FlowchartFragment":
        """Require unique ids, links between existing distinct elements, and coherent flow.

        Notes sit outside the flow, so only annotations touch them. A start has
        no incoming transition and an end has no outgoing one.
        """
        element_ids = [element.id for element in self.elements]
        if len(set(element_ids)) != len(element_ids):
            raise ValueError("element ids must be unique")
        connection_ids = [connection.id for connection in self.connections]
        if len(set(connection_ids)) != len(connection_ids):
            raise ValueError("connection ids must be unique")
        kinds = {element.id: element.kind for element in self.elements}
        for connection in self.connections:
            if connection.source not in kinds or connection.target not in kinds:
                raise ValueError(f"connection {connection.id} references a missing element")
            if connection.source == connection.target:
                raise ValueError(f"connection {connection.id} cannot connect an element to itself")
            if connection.kind == "annotation" and "note" not in (
                kinds[connection.source], kinds[connection.target]
            ):
                raise ValueError(f"annotation {connection.id} must attach a note")
            if connection.kind == "transition":
                if "note" in (kinds[connection.source], kinds[connection.target]):
                    raise ValueError(f"transition {connection.id} cannot link a note; use an annotation")
                if kinds[connection.target] == "start":
                    raise ValueError(f"transition {connection.id} cannot enter a start")
                if kinds[connection.source] == "end":
                    raise ValueError(f"transition {connection.id} cannot leave an end")
        return self


class Flowchart(FlowchartFragment):
    """Hold the complete canvas graph and its saved viewport."""

    viewport: Viewport = Field(default_factory=Viewport)


class Gameplan(FlowchartModel):
    """Group a patch's planning artifacts; it holds only the flowchart for now."""

    flowchart: Flowchart = Field(default_factory=Flowchart)


class PatchWorkspace(FlowchartModel):
    """Portable player-named workspace document, identical to its JSON export."""

    schema_version: Literal["flowchart.v1"] = "flowchart.v1"
    name: WorkspaceName
    patch: PatchLabel | None = None
    set_number: SetNumber | None = None
    gameplan: Gameplan = Field(default_factory=Gameplan)


class WorkspaceRecord(FlowchartModel):
    """Return one workspace document with its storage identity and revision.

    Database records use a UUID id; checked-in JSON records use their file slug
    and are read-only in the UI.
    """

    id: str
    revision: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: WorkspaceSource
    workspace: PatchWorkspace


class WorkspaceSummary(FlowchartModel):
    """List one workspace in the Flowchart rail without its canvas graph."""

    id: str
    name: str
    patch: str | None = None
    set_number: int | None = None
    revision: int
    updated_at: datetime | None = None
    source: WorkspaceSource


class WorkspaceList(FlowchartModel):
    """Return every workspace summary available from one source."""

    source: WorkspaceSource
    workspaces: list[WorkspaceSummary]


class WorkspaceCreateRequest(FlowchartModel):
    """Create an empty named database workspace for one patch and set."""

    name: WorkspaceName
    patch: PatchLabel | None = None
    set_number: SetNumber | None = None


class WorkspaceSaveRequest(FlowchartModel):
    """Replace a database workspace document when ``revision`` is still current."""

    revision: Annotated[int, Field(ge=1)]
    workspace: PatchWorkspace


class WorkspaceRenameRequest(FlowchartModel):
    """Rename a database workspace when ``revision`` is still current."""

    revision: Annotated[int, Field(ge=1)]
    name: WorkspaceName


class WorkspaceImportRequest(FlowchartModel):
    """Copy a portable workspace document, usually a checked-in JSON one, into the database."""

    workspace: PatchWorkspace


class WorkspaceExport(FlowchartModel):
    """Report where an export was written and return the exported document."""

    path: str
    workspace: PatchWorkspace


class GroupRecord(FlowchartModel):
    """Return one saved group from the Flowchart library.

    Used by the library tab to list, preview, and insert reusable fragments.
    """

    id: str
    name: str
    set_number: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    fragment: FlowchartFragment


class GroupList(FlowchartModel):
    """Return every saved group, most recently updated first."""

    groups: list[GroupRecord]


class GroupCreateRequest(FlowchartModel):
    """Save a selection of canvas elements as a named reusable group.

    ``fragment`` must hold at least one element; positions are expected to be
    relative to the group's top-left corner so insertion can place it anywhere.
    """

    name: WorkspaceName
    set_number: SetNumber | None = None
    fragment: FlowchartFragment

    @model_validator(mode="after")
    def require_elements(self) -> "GroupCreateRequest":
        """Refuse empty groups, which would insert nothing."""
        if not self.fragment.elements:
            raise ValueError("a group needs at least one element")
        return self


class GroupRenameRequest(FlowchartModel):
    """Rename a saved group."""

    name: WorkspaceName
