# Flowchart patch workspaces

The **Flowchart** desktop tab is a private, player-authored planning canvas.
Each TFT patch shifts the meta, so players create and name a *patch
workspace*, drag units, items, and augments onto a canvas, and build a
decision graph: the strategic states they play toward, the actions they take,
the decisions that choose between lines, the guarded transitions between them,
and situational notes. Workspaces are never discovered automatically.

The node and edge roles borrow from UML activity diagrams so a diagram can say
what the player is doing, what is being decided, when a transition applies, and
which state comes next. The canvas stays freeform: only the few rules listed
under [validation](#validation) are enforced.

The tab loads the standalone `/flowchart` page of the Vite React application in
its own sandboxed `WebContentsView`, the same way Rolldown and Compositions do
(see [Electron desktop](desktop.md)). Browser users can open `/flowchart`
directly. It touches no match data, projections, or assistant tools, so the
raw-store → projection → bounded-tool boundary is unaffected.

## Data model

`app/backend/src/services/flowchart/models.py` defines the portable document.
All models reject unknown fields.

| Model | Purpose |
| --- | --- |
| `PatchWorkspace` | `schema_version: "flowchart.v2"`, `name`, optional `patch` and `set_number`, and a `gameplan`. This is exactly what a JSON export contains. |
| `Gameplan` | Holds the `flowchart`; kept separate so later planning artifacts can be added. |
| `Flowchart` | A `FlowchartFragment` plus the saved `viewport` (`x`, `y`, `zoom`). |
| `FlowchartFragment` | `elements` and `connections`, validated as one graph. Saved groups store just a fragment. |
| `FlowchartElement` | `id`, `kind`, `position`, optional `size`, `title`, optional `stage_hint`, `entities`, `text`, `parent_id`, `locked`, and optional group `tint`. |
| `FlowchartConnection` | `id`, `source`, `target`, `kind`, `condition` (the guard), `notes`, and optional `source_handle` / `target_handle`, `waypoints`, and `label_offset`. |
| `EntityRef` | `category` (`unit`, `item`, `augment`) and `api_name`. |

Element kinds and how the canvas draws them:

| Kind | Role | Shape | Contents |
| --- | --- | --- | --- |
| `plan` | Strategic state or line: an opener, composition, or pivot. | Card with a tinted **State** header and a stage badge | `title`, `stage_hint` such as `2-1`, up to 40 entity chips. |
| `action` | Something the player does, such as slamming items or rolling at 4-1. | Rounded rectangle captioned **Action** | `title`, `stage_hint`, up to 40 entity chips. |
| `decision` | A question that picks a branch; with several incoming links it is a merge. | Resizable diamond | `title` holds the question. |
| `fork` | Splits one path into parallel ones, or joins them back. | Solid bar; horizontal when wider than tall | Nothing. |
| `start` | Where the gameplan begins. | Filled dot | Nothing. |
| `end` | Where a line finishes. | Ringed dot | Nothing. |
| `entity` | One standalone dropped icon. | Tile | Exactly one `EntityRef`. |
| `note` | A situational annotation. | Note with a folded corner | `text`. |
| `group` | A visual container in this activity diagram. | Named, tinted frame or collapsed card | Children refer to its `parent_id`; nested positions are relative to the parent. |

Connection kinds:

- `transition` moves the flow from one element to the next. Its `condition` is
  the guard, drawn as `[guard]` on the edge. Its `notes` are situational detail
  shown in a callout under the guard, so notes can belong to a transition as
  well as to a node.
- `annotation` attaches a note node to any element. It must have a note at one
  end, and the canvas draws it dashed and picks this kind automatically for any
  link that touches a note.

Every node has four connection points, one per side, and any side can start
or end a link. The side a link uses is saved in `source_handle` /
`target_handle` (`top`, `right`, `bottom`, `left`). Links saved with `null`
sides, as earlier documents were, are drawn from the right side to the left
side. A link's direction is always from where the drag started to where it
ended.

### Validation

The backend enforces only what keeps a document coherent:

- Element and connection ids are unique, and every connection joins two
  existing, distinct elements.
- Only `plan` and `action` hold entity chips; an `entity` holds exactly one;
  other kinds hold none.
- A transition cannot touch a note (use an annotation), enter a `start`, or
  leave an `end`.
- At most 400 elements and 800 connections, with bounded text lengths.
- Every parent exists and is a group; containment is acyclic. Authored
  connections attach to activity elements, rather than visual containers.
- Coordinates and routing offsets are finite and bounded to ±1,000,000;
  dimensions are positive and at most 4,000. Routes have at most 64 manual
  waypoints. Group tint is a six-digit hex color.

Everything else, including decisions without guards, several starts, or
unconnected nodes, is allowed. The canvas refuses links the backend would
reject, and outlines a decision branch's guard pill in gold while it is empty.

Legacy `flowchart.v1` workspaces and library fragments are accepted and
normalized in memory with empty routing metadata, no parent, and no lock.
Responses and downloads emit `flowchart.v2`. Reading a v1 document does not
rewrite its row/file or advance its revision; stored JSON upgrades only on an
ordinary save, import, rename, or explicit export. DOM measurements, search,
collapse, focus, and named views do not autosave content.

Only entity API names are stored; names and images are resolved at render
time, so a patch-bundle change never breaks a document.

Panel conveniences (snap-to-grid, minimap visibility, and link style) use
`tft.flowchart.panel` in localStorage. Collapse and named focus views use
`tft.flowchart.views:<source>:<workspace-id>`. These are personal browser
settings, separate from the workspace document and its revision. The latest
pan/zoom is also personal state in that key; it falls back to the exported
viewport when no personal viewport has been saved.

## Sources

Two sources hold workspaces:

- **Database** (default, editable). The runtime table `chat_tft_dev_workspaces`
  (`db/models/workspaces.py:DevWorkspace`) stores `workspace_id`, a unique
  `name`, `revision`, `created_at`, `updated_at`, and the `document` JSON. It is
  created at startup with the other `RUNTIME_MODELS`; see
  [persistence](../data/persistence-and-analytics.md#private-flowchart-workspaces).
- **Checked-in JSON** (read-only). One `gameplans/<slug>.json` file per
  `PatchWorkspace` at the repository root. Its id is the file slug. Files with
  invalid names or contents are skipped in the list.

`[chat] flowchart_source = database | json` in `chat_tft.ini` selects the
default (see [configuration](../configuration.md#flowchart-workspaces)); the
value is published by `/api/config`. The rail's **Database** / **Checked-in
JSON** switch starts from it, and every workspace route accepts `?source=` as an
override.

JSON workspaces open read-only. **Import to database** copies the document into
the database so the database stays the single place edits happen. **Import JSON
file** in the rail does the same for a file chosen from disk.

## Editing and saving

Database workspaces autosave. Edits are debounced for about 800 ms and sent
with the revision the page last saw. The server updates the row only while its
stored revision still matches, so a save from a stale page returns 409 and the
page shows a conflict banner with **Reload**. Duplicate names also return 409.
Renaming edits the workspace title in the header; deleting asks for
confirmation and does not remove exported files.

On the canvas:

- **Left-drag** on empty canvas draws a selection box. Nodes fully inside it,
  and the links between them, are selected. The canvas scrolls when the box
  reaches its edge. **Left-click** selects, and **left-drag** on a node moves
  it (or the whole selection). **Left-click on empty canvas** clears all selected
  nodes and connections, including a large boxed selection.
- **Right-drag** (or middle-drag) pans the canvas and preserves the selection.
  A **short right-click** opens common commands next to the cursor on release:
  undo/redo, adding a node at the click position, and selection operations such
  as grouping, duplicating, locking and deleting. Right-clicking an unselected
  node or connection targets it; right-clicking selected objects or empty canvas
  preserves the current selection. A hold longer than 350 ms or movement beyond
  5 pixels does not open a menu. The popup stays inside the viewport and closes
  after choosing a command, clicking elsewhere, or pressing Escape. Read-only
  workspaces disable document mutations. The browser context menu is suppressed
  on the canvas. The scroll wheel zooms.

- The toolbar's **Start**, **State**, **Action**, **Decision**, **Fork / join**,
  **End**, and **Note** buttons add that node at the visible center. New
  decisions start at 128×96, new fork bars as a horizontal 160×10 bar for
  top-to-bottom flow, and new notes 192 wide, growing down with their text.
- Drag a sidebar tile onto a state or action to add a chip, or onto empty
  canvas to create an entity node. Hover a chip to remove it. More than 12
  chips collapse behind a **+N** chip that expands the node.
- Hover or select a node to show its four connection points, and drag from
  one to a point on another node to connect them.
- A link's guard is a `[guard]` pill on the line. Empty guards stay hidden
  until the link is selected, except on decision branches. The note button on
  the pill opens the transition's notes in a callout under it. The button is
  gold when the link has notes.
- **Shift**, **Ctrl**, or **Cmd** + click adds to the selection.
- **Backspace** or **Delete** removes the selection. Ordinary container deletion
  ungroups it; **Delete group and contents** explicitly removes descendants.
- **Save group** in the toolbar saves the selected nodes to the library; see
  [saved groups](#saved-groups).

Links use obstacle-aware orthogonal routing by default. The **Right-angle /
Curved** toggle retains the viewer's preferred automatic style. Manual routes
remain orthogonal. The worker changes routes without moving authored nodes;
while dragging or awaiting a result, inexpensive provisional paths are shown.
Attachments are distributed along shared sides, including fork/join bars, and
A* routing penalizes turns, shared segments, and crossings. Automatic guards
try clear positions away from nodes and prior labels. Impossible geometry keeps
a usable path and displays a nonblocking overlap warning.

### Layout and geometry

**Layout diagram** explicitly arranges the diagram using pinned elkjs 0.11.0
and ELK layered compound layout. **Layout selection** arranges selected siblings
and the descendants of selected groups; mixed-parent selections are disabled.
Choose **Top to bottom** (default) or **Left to right**. Layout uses explicit or
measured sizes and side-constrained ports. Selection layout preserves every
unselected position and centers the new bounds around the selection's old
center. Layout clears manual bends on connections affected by arranged nodes.
Ordinary text edits, routing, collapse and focus never arrange nodes.

**Align / distribute** offers left/center/right, top/middle/bottom and both
spacing directions for siblings. Distribution requires at least three objects.
Dragging shows alignment guides. **Lock position** prevents dragging, resizing
and arranging that object's geometry. A group containing a locked descendant
cannot move as a unit; layout keeps that group's subtree fixed. Text editing
remains available.

Select a connection to drag an orthogonal segment or its visible bend grip.
Use the guard's grip to drag its label. **Reset route/label placement** clears
manual bends and label offsets on selected connections (or connections touching
selected elements). Manual placement persists in the document. Reconnect a
connection endpoint by dragging it to a valid handle; identity, guard and notes
are retained. Proxy endpoints require expanding their groups first.
**Insert action** splits a selected transition into two links: the original ID,
guard, notes and label offset stay on the incoming link, and the outgoing link
starts unlabelled.

Routing and layout run in workers with progress feedback. New geometry jobs
terminate obsolete workers, and generation checks reject late responses. Editing
during layout cancels its result so it cannot overwrite newer document changes.

### Readable text and transactions

Titles, questions, guards and notes render as wrapped text. Double-click or
**Enter** opens the focused field; **Escape** cancels. **Enter** commits a
single-line field, **Ctrl/Cmd+Enter** commits multiline fields, and blur commits.
Typing is a local draft until commit, so a committed field is one undo step.
Default-sized nodes grow with content; explicit sizes stay explicit and show
**Overflow · Fit to content** when needed. **Fit to content** returns the node
to content sizing. The collapsible **Properties** panel shows complete text,
entity lists and connection details, including for collapsed proxy connections.

The canvas owns one canonical document and up to 100 history transactions per
open workspace. A drag, resize, layout, group command, paste or committed text
edit is one transaction. **Undo / Redo**, **Ctrl/Cmd+Z**, **Ctrl/Cmd+Shift+Z**, and
**Ctrl+Y** restore documents through the same revision-checked autosave.
**Ctrl/Cmd+A** selects visible objects; **Ctrl/Cmd+D** duplicates at the last
canvas pointer position (or visible center). Browser **Cut / Copy / Paste**
events carry a versioned, validated fragment as clipboard data and plain text;
no desktop clipboard-read permission is required. Text editors retain normal
text clipboard and undo behavior. Copying a container includes descendants and
internal links; copying children alone detaches them from unselected parents.
Paste uses fresh IDs, selects copied roots, and shifts root positions and manual waypoints.

### Nested visual groups

**Group** requires two or more selected siblings and creates a named, tinted
container. Rename and tint it in Properties. **Ungroup**, **Add to group**, and
**Remove from group** are available in the selection toolbar and context menu;
choose the destination group explicitly. Overlap never changes membership.
Moving a container moves descendants through React Flow parent positioning;
resizing cannot clip children, and explicit content edits grow containers as
needed. Ungrouping preserves child world positions and all connections.

**Collapse group** replaces its frame with a compact named card and descendant
count. Internal connections disappear from the view; each external connection
gets a separate temporary group-boundary endpoint. Original endpoints, guards,
notes, IDs, and manual routes remain in the canonical document for expansion.
Proxy connections are selectable and inspectable. Collapse is personal state;
saving while collapsed still saves every original element and connection.
Groups organize one activity diagram; they do not create child diagrams, called
activities, or state machines.

### Search and personal focus views

**Search diagram** covers titles, notes, guards, stages, group names and resolved
entity names. A result expands its collapsed ancestors and centers the target;
connection results reveal both original endpoints. **Selection**, **Upstream**,
**Downstream**, and **Both** focus modes traverse transition links with cycle
protection, include associated annotations and ancestor containers, and dim
unrelated objects. **Reset focus** or Escape clears focus.

**Save view** records a name, viewport, focus mode/seeds and collapsed groups in
localStorage for that workspace/source. **Open view** restores it; **Clear saved
views** removes those personal views. Deleted object references are pruned.
Search, focus, collapse, named views, selection and copying remain available on
read-only JSON workspaces; document mutations are disabled.

### Visual system

Every outline, handle, and link uses the same tokens, defined as
`--fc-*` custom properties on `.flowchart-view` in `flowchart.css`: stroke
width, radii, text sizes, and one color per role (state, action, decision,
flow, note), all taken from `theme.css`. Outlines are SVG paths sized to each
node's measured box (`Outline` in `nodes.jsx`), so the diamond and folded note
stay crisp at any size and share one selection halo. Rules that restyle React
Flow's own handles, resizer, and edge paths sit outside the stylesheet's
`@layer`, because React Flow's unlayered stylesheet would otherwise override
them.

## Saved groups

The library holds reusable, player-named groups of elements: an action with a
prewritten label, a state with its units already attached, or a whole branch
of states, decisions, and links. It is shared by every workspace.

- **Save:** select elements on the canvas (a box selection works well), choose
  **Save group**, and name it. The group keeps the selected nodes and only
  the links between them. Selecting a visual container also includes all its descendants. Unselected
  parents are detached; root positions and manual waypoints shift to the
  fragment origin, while nested child positions remain relative to parents. Saving also works from a read-only JSON workspace, since it
  does not edit that workspace.
- **Use:** the palette's **Groups** tab lists each group with its contents
  ("2 states · 1 action · 1 link") and entity thumbnails. Drag a card onto the
  canvas to paste it where it lands, or choose **Insert** to paste it at the
  visible center. Every paste gets fresh ids, so a group can be used many
  times, and the pasted copy is selected so it can be moved straight away.
  Pasted copies are independent: editing or deleting the group later never
  changes them.
- **Manage:** rename or delete a group from its card. Search filters groups by
  name.
- **Sets:** a group records the workspace's `set_number` when saved. Cards
  from a different set show a **Set N** badge, because their unit, item, and
  augment chips may not exist in the current set.

Library entries live only in `chat_tft_dev_flowchart_groups` and are separate
from workspace exports. Visual containers and their nested membership are part
of each workspace document and its export. Inserting a library entry copies
nested containers and descendants with fresh IDs; inserted fragments are
independent.

## Export

**Export JSON** writes `gameplans/<slug>.json` on the server, where the slug is
the lowercase hyphenated workspace name, and also downloads the same document in
the browser. The file is written to a temporary sibling and moved into place
with `os.replace`, so readers never see a partial file. Re-exporting a workspace
overwrites its file; two names with the same slug share a file. Commit the file
to share a gameplan through the repository.

## Entity sidebar and images

`GET /api/assets/catalog?patch=&set_number=` lists the sidebar roster from local
downloads only (see [local entity images](../architecture/web-runtime.md#local-entity-images)):

- `units`: shop champions (cost 1–5 with traits), grouped by cost.
- `items`: recipe components and plannable finished items, with a `type` from
  `TFTNameResolver.classify_item` (`component` for basic components).
  Consumables and other unclassified entries are hidden.
- `augments`: the set's augment list.

The palette's fourth tab, **Groups**, holds the [saved groups](#saved-groups)
rather than catalog entities.

The workspace's `patch` and `set_number` select the bundle, then
`[chat] set_number`, then the newest downloaded set. Entities without a
downloaded image have `src: null` and render as text tiles.

Augment icons need their own download group:

```bash
uv run python scripts/download-assets.py --patch latest --set 17 --groups augments
```

This writes `manifest-augments.json` next to the existing manifests, which the
asset service already reads. `POST /api/assets/resolve` also accepts
`kind: "augment"` with `role: "icon"`.

## HTTP API

Routes live in `app/backend/api/routes/flowchart.py` under `/api/flowchart`.
Handlers are synchronous, so database and file work runs off the event loop.

| Method and path | Behavior |
| --- | --- |
| `GET /workspaces` | List summaries from the source. |
| `POST /workspaces` | Create an empty database workspace (`name`, optional `patch`, `set_number`). |
| `GET /workspaces/{id}` | Open one workspace record. |
| `PUT /workspaces/{id}` | Save `{revision, workspace}`; 409 on a stale revision or duplicate name. |
| `PATCH /workspaces/{id}` | Rename with `{revision, name}`. |
| `DELETE /workspaces/{id}` | Delete a database workspace. |
| `POST /workspaces/{id}/export` | Write `gameplans/<slug>.json`; returns `{path, workspace}`. |
| `POST /workspaces/import` | Copy `{workspace}` into the database. |
| `GET /groups` | List saved groups, most recently updated first. |
| `POST /groups` | Save `{name, set_number, fragment}`; 409 on a duplicate name, 422 for an empty or invalid fragment. |
| `PATCH /groups/{id}` | Rename a group with `{name}`. |
| `DELETE /groups/{id}` | Delete a group. |

Missing workspaces or groups return 404. Edits against the JSON source return
400. The group routes always use the database and ignore `?source=`.

## Source layout and tests

| Path | Role |
| --- | --- |
| `app/backend/src/services/flowchart/` | Models, service operations, and storage helpers. |
| `app/frontend/src/flowchart/` | `Flowchart.jsx` (rail and save loop), `EntitySidebar.jsx`, `FlowchartPanel.jsx` (React Flow canvas), `nodes.jsx`, `edges.jsx`, `TextField.jsx`, `document.js` (validated commands/history), `projection.js` (personal views), `layout.js` / `layout.worker.js`, `routing.js` / `routing.worker.js`, `utils.js` (shared helpers), `api.js`, `models.js` (Zod mirrors), `flowchart.css`. |
| `../desktop/workspace.mjs`, `../desktop/main.mjs` | The `flowchart` view and **Ctrl+4** menu entry. |

```bash
uv run pytest -q tests/test_flowchart_api.py tests/test_flowchart_persistence.py tests/test_entity_assets.py
npm --prefix app/frontend test
npm --prefix app/frontend run build
npm --prefix ../desktop test
```

`tests/test_flowchart_persistence.py` runs against the isolated `RDS_TEST_*`
database and skips when it is unavailable; the API tests use a disposable
SQLite table and a temporary `gameplans/` directory.


Geometry/command tests in `app/frontend/src/flowchart/document.test.js` cover
nested manipulation, collapse, cyclic focus, clipboard validation, locks,
reconnection, insertion, routing and measured selection/compound layout.
`TextField.test.jsx` covers keyboard commits/cancellation; `Flowchart.test.jsx`
covers read-only behavior, autosave/history, personal views and stale layout.
See [browser smoke and large fixture](../development/testing-and-evals.md#flowchart-editor-validation)
for production-worker validation without live workspaces.
