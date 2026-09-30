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
| `PatchWorkspace` | `schema_version: "flowchart.v1"`, `name`, optional `patch` and `set_number`, and a `gameplan`. This is exactly what a JSON export contains. |
| `Gameplan` | Holds the `flowchart`; kept separate so later planning artifacts can be added. |
| `Flowchart` | A `FlowchartFragment` plus the saved `viewport` (`x`, `y`, `zoom`). |
| `FlowchartFragment` | `elements` and `connections`, validated as one graph. Saved groups store just a fragment. |
| `FlowchartElement` | `id`, `kind`, `position`, optional `size`, `title`, optional `stage_hint`, `entities`, `text`. |
| `FlowchartConnection` | `id`, `source`, `target`, `kind`, `condition` (the guard), `notes`, and optional `source_handle` / `target_handle`. |
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

Everything else, including decisions without guards, several starts, or
unconnected nodes, is allowed. The canvas refuses links the backend would
reject, and outlines a decision branch's guard pill in gold while it is empty.

These kinds and the handle fields were added without changing
`schema_version`; every earlier `flowchart.v1` document is still valid.

Only entity API names are stored; names and images are resolved at render
time, so a patch-bundle change never breaks a document.

Panel conveniences (snap-to-grid, minimap visibility, and link style) are
per-viewer browser settings in `localStorage`, not part of the document.

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
  it (or the whole selection).
- **Right-drag** (or middle-drag) pans the canvas; the browser context menu is
  suppressed there. The scroll wheel zooms.

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
- **Backspace** or **Delete** removes the selection.
- **Save group** in the toolbar saves the selected nodes to the library; see
  [saved groups](#saved-groups).

Links are drawn as right-angle paths with rounded corners by default. The
**Right-angle / Curved** toolbar toggle switches to curves. Like snap-to-grid
and minimap visibility, it is a per-viewer browser setting.

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
  the links between them. Positions are stored relative to the group's
  top-left corner. Saving also works from a read-only JSON workspace, since it
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

Groups live only in the database (`chat_tft_dev_flowchart_groups`); they are
not part of workspace exports.

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
| `app/frontend/src/flowchart/` | `Flowchart.jsx` (rail and save loop), `EntitySidebar.jsx`, `FlowchartPanel.jsx` (React Flow canvas), `nodes.jsx`, `edges.jsx`, `api.js`, `models.js` (Zod mirrors), `flowchart.css`. |
| `../desktop/workspace.mjs`, `../desktop/main.mjs` | The `flowchart` view and **Ctrl+4** menu entry. |

```bash
uv run pytest -q tests/test_flowchart_api.py tests/test_flowchart_persistence.py tests/test_entity_assets.py
npm --prefix app/frontend test
npm --prefix ../desktop test
```

`tests/test_flowchart_persistence.py` runs against the isolated `RDS_TEST_*`
database and skips when it is unavailable; the API tests use a disposable
SQLite table and a temporary `gameplans/` directory.
