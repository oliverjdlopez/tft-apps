# Web Runtime and Browser UI

FastAPI provides the application lifecycle and HTTP boundary. The frontend is a
Vite-built React application served as static assets, while service modules
adapt domain behavior for routes.

At backend import, `common.disk_profile` instruments Python file opens and common
path-based filesystem operations. It appends request-correlated records to
`profiles/disk_usage.txt` at the repository root. File-session records summarize
read/write call counts, binary byte counts or encoded-text byte estimates, I/O
time, and total open-to-close time;
metadata, directory, and mutation operations are logged individually. This
captures Python site-process access, including static asset reads, but does not
measure database storage I/O, browser filesystem activity, or operations hidden
inside external subprocesses. Profiling output is diagnostic and best-effort.
Chat request stage timings are appended as JSONL records to
`profiles/chat_timing.jsonl`. Each record separates context selection, skill
selection, instruction assembly, agent setup, first stream chunk, first model
event, first text delta, and total request time. Missing stage values mean the
request ended before that stage completed; interrupted streams are recorded as
such. The output is local diagnostic data and is ignored by Git.

## Backend composition

`api/app.py:create_app` assembles routes, serves `app/frontend/dist`, installs
local tracing, attempts to validate and warm the application database, and can
start query-table catch-up. Route modules under `api/routes/` validate HTTP
inputs and delegate to `services/`:

- `chat_service.py` owns model selection, API-key checks, configuration
  payloads, streamed chat execution, and `StreamingResponse` construction. Its
  `/api/config` model options come from `domain.model_catalog.chat_model_specs`,
  which supplies the labels and IDs shown in the chat model dropdown. Labels
  include the exact model ID and are derived from it, so they cannot advertise a
  different model version than the submitted value. The latest-model option uses
  the current `OpenAIModels.LATEST` ID alongside the curated model choices.
- `display_service.py` supplies explorer views for models, databases, tools,
  and upstream APIs.
- `/api/shared-media` exposes immutable shared file publication, discovery,
  metadata, and verified content through the independently vendored catalogue.
  See [suite media sharing](../../../docs/shared-media.md) for the cross-backend
  contract and VOD library integration.
- `services/flowchart/` stores player-authored patch workspaces for the
  `/api/flowchart` routes; see [Flowchart](../apps/flowchart.md).
- the remaining services adapt assistants, tasks, rolldown analysis, tracing,
  ingestion, and streaming events to the HTTP layer.

Evaluations run in a separate local Langfuse deployment and Python experiment
service under `evals/langfuse/`. Its native UI edits datasets and prompt versions,
triggers real agent experiments, and displays traces and scores. Each run exports
frozen definitions for Git review. Context and skill resources remain repository
files. The former Evals tab and `/api/evals` routes remain removed.

The assistant-spec editor validates the graph and retains revision conflict
detection. Suite labels come from `evals/config.py`, which reads the local
Langfuse snapshot catalog without contacting the platform. Saving a production
spec does not start evaluations. Evaluation prompt candidates affect only fresh
eval graphs; normal conversations continue using repository specs. See
[Tests and evaluations](../development/testing-and-evals.md).

`scripts/start.py` launches the configured UI service. Installed command names
are declared in `pyproject.toml`.

The [Electron desktop application](../apps/desktop.md) lives at the suite root under
`../desktop/` and starts this same FastAPI application from the checkout. Normal
launch rebuilds and loads the production UI; development launch starts Vite
with hot reload and proxies to the managed backend. Desktop owns its service
processes, binds them to loopback, and stops them on Quit. Frontend components,
HTTP contracts, configuration loading, and backend resource paths are shared
with the browser application. For WSL development on Windows, the native
Electron shell starts services in the existing WSL distribution and checkout,
using pipe guardians for shutdown and service identity probes to validate
Windows localhost forwarding. Only desktop shell files and Windows Electron
dependencies are cached on Windows; Python and frontend dependencies stay in WSL.

## Streaming protocol

The browser posts chat requests to `/api/chat`. Plain assistant text and
bracket-delimited JSON events share one response stream. The event boundaries
are defined by `services.streaming.STREAM_EVENT_PREFIX` and
`STREAM_EVENT_SUFFIX` and mirrored by `src/streaming.js`. Tool, handoff, trace,
and context events are rendered in the Activity panel.
Callers may set `X-Chat-Assistant` to the exact name of a registered repository
assistant to use that assistant as the root of the streamed graph. An omitted
header preserves the `chat` root; blank or unknown names are rejected before a
stream begins. Routing changes the root specification, so its instructions,
tools, handoffs, and trace metadata remain governed by the assistant registry.
`/api/config` publishes the default and discovered assistant names. The chat
header renders them in an **Assistant** selector immediately left of the Model
selector, persists the user's choice locally, and supplies that name through
the routing header on each request. On narrow screens, the header actions wrap
so both selectors and conversation controls remain reachable.
The adapter emits a `text_part_complete` event after each Responses API output
text part. The browser buffers its deltas until that semantic boundary, then
appends the complete part with two leading line breaks, a
`**response <count>**` Markdown label, and two line breaks before its content.
The count restarts for every assistant response; Activity-panel events never
receive this chat-only formatting. HTTP response chunks are not used as part
boundaries.
Chat Activity trace links open the encoded trace-detail URL rather than the
dashboard index.

## Main navigation

The React application has three primary destinations: **Chat**, **Workflows**,
and **Developer**. Rolldown runs at `/rolldown` as a standalone page without
the ChatTFT sidebar, also linked from Developer → Status. The
[Flowchart](../apps/flowchart.md) patch workspace runs at `/flowchart` as another
standalone page, loaded lazily so React Flow stays out of the main chat bundle. Workflows groups Assistants and Tasks with a
category selector; changing category resets the runner's inputs and results.
Developer groups Status, Models, Tools, Raw API, Prompt tuning, and Specs.
Status shows scoped/raw board coverage and links to the separately started
CloudBeaver and Langfuse services. The global database availability warning
remains visible across destinations.

The embedded database row browser has been removed. Use the desktop Database
tab or [local CloudBeaver](http://localhost:8979) from a browser; see
[database workspace setup](../apps/desktop.md#database-workspace-cloudbeaver).
The existing database HTTP endpoints remain available. Langfuse owns evaluation
work; production spec editing, application tool invocation, upstream API probes,
and response-continuation experiments remain in Developer. Chat retains live
Activity and OpenAI trace links.

Saved legacy navigation selections migrate to the corresponding Workflows or
Developer section. A saved Database section falls back to Status; retired Evals
and unknown primary destinations fall back to Chat.

## Shared interface

ChatTFT, Compositions, Rolldown, and Flowchart use locally installed shadcn/ui components
(New York, Radix, neutral light), Tailwind CSS 4, and Lucide icons. ChatTFT owns the
canonical light theme with distinct pastel panels and dialogs; the desktop shell
mirrors its palette. The independent
VOD Review and Wisps views share the sibling VOD application and its own theme.
Navigation, tool payloads, streaming, specialist renderers, and revision checking
retain their existing contracts. See [shared UI conventions](../development/shared-ui.md)
for component provenance, CSS layering, and the update procedure.

Compositions at `/compositions` uses a rail-and-workspace layout: a persistent
left rail holds **New experiment**, the saved run history with live status, and
the display fixtures entry, while the main column shows the setup form, the
selected run, or fixtures. A selected run exposes Families, Boards, Diagnostics,
and Compare tabs. Below 960px the rail stacks above the workspace and family
browsing becomes a native selector. Example inspection opens the dedicated board
panel; display fixtures remain a labeled secondary view. See the
[Compositions layout conventions](../development/shared-ui.md#compositions-workspace-layout)
for state retention, evidence denominators, and component ownership.

## Frontend loading model

The browser application is managed by `app/frontend/package.json` and bundled
with Vite. `src/main.jsx` imports React, the markdown/sanitization dependencies,
the tab modules and application styles. The production build
is written to the ignored `app/frontend/dist` directory. FastAPI returns a clear
503 message from `/` and non-API HTML fallback routes when that build is absent;
it never invokes npm during startup.

For local frontend iteration, run the Vite development server from
`app/frontend`. Its `/api` and `/static` requests proxy to the configured
FastAPI port (`127.0.0.1:8300` by default). The committed lockfile makes
`npm ci` reproducible; CI uses Node 22.

The **Prompt tuning** page is a local developer console for OpenAI Responses
API continuation experiments. It posts a prior `response_id`, a new user
message, and optional model/instruction/sampling limits to
`/api/response-tuning/continue`. The route reads `OPENAI_API_KEY` only on the
server, retrieves the parent response for inspection, optionally lists its
stored input items, and creates the branch with `previous_response_id` rather
than reconstructing chat history. Its non-streaming result includes the exact
request, parent metadata, returned output items (including tool calls/results
when present), usage, response ID, latency, and API errors.

The Rolldown page labels its comparison inputs **Dimension 1 (x-axis)** and
optional **Dimension 2 (y-axis)**. **Dimension 3 (z-axis)** represents target-hit
probability in the 3D surface, also encoded as color in the heatmap. These are
display labels; the simulation API retains its `sweep`/`sweeps` payload fields.

The Developer Tools tab builds its argument forms from the backend-provided
`invocation_schema`, whose required fields match Python/Pydantic call defaults.
It still exposes the SDK's strict `input_schema` separately for exact
model-facing schema inspection.

Chat answers combine Markdown with backend-resolved evidence cards. A
`presentation` stream event contains a typed resolved presentation: an ID,
evidence bundle, and validated display specification. A `presentation_error`
event preserves the answer and marks the view unavailable. The stream reads
successful presentation objects from the invocation store rather than trusting
model-authored cells or applying model-facing rounding.

React renders three application-owned displays: static tables, placement
distributions with an accessible table alternative, and locally interactive
tables. Sorting, search, categorical section grouping, displayed-row limits,
and reset operate on the loaded slice without network requests or aggregate
calculations. The row limit defaults to every loaded row and can be set from one
through the number loaded. Source, population, warnings, and page coverage
remain attached. The old investigation endpoint remains removed; there is no
A2UI runtime.

Interactive controls open from an Explore table disclosure; chart labels do not
shrink with the chart width. Activity starts closed when it would cover the
answer on a narrow screen.

Chat stays mounted while another tab is active, preserving messages, in-flight
responses, evidence, per-card view state, and reading positions. New output
follows the bottom only while the user is following it; hidden panes defer
scrolling until chat is visible again. New conversation clears completed
displays; browser reload starts fresh. The composer retains an optional starter
prompt feature, currently configured with an empty list. Follow-up requests
contain text history only, without evidence bundles or frontend state. Evidence references are scoped
to one backend invocation and are never reused as cross-turn server handles.


## Startup and degraded mode

Startup validates the configured app RDS target and warms its pool. Missing,
partial, or unreachable database configuration leaves UI-only features
available and exposes a credential-safe warning through `/api/config`.
Database-backed operations remain unavailable until the target is usable.

`rebuild_query_tables_on_startup` accepts off/false, `sync`, or `async` modes.
The enabled modes perform ledger catch-up, not a full rebuild. An asynchronous
startup task is cancelled during shutdown if it is still running.

The ingestion HTTP model is an explicit allowlist. It exposes safe run options
without accepting DSNs, hosts, credentials, or arbitrary environment maps.
Browser-history fallback applies only to non-`/api/` HTML requests.

## Validation surfaces

Backend coverage for the web boundary includes:

```bash
uv run pytest -q tests/test_start_cli.py tests/test_chat_service.py tests/test_tracing_service.py
uv run pytest -q tests/test_config.py tests/test_ingestion_cli_config.py
```

Frontend behavior is covered with Vitest, jsdom, and Testing Library:

```bash
cd app/frontend
npm ci
npm test
npm run build
```

## Desktop-only Langfuse workspace

Electron adds application and external-service tabs outside the React application
using independent `WebContentsView` instances. ChatTFT, Rolldown, and the configurable
Compositions workspace share one backend; Force Reload on any of them restarts
that backend and reloads all enabled application views. Switching
tabs preserves each view’s in-memory state. `../desktop/workspace.mjs` owns view selection, isolated
Langfuse navigation and login storage, retry state, and child-renderer cleanup.
The local shell alone receives a fixed-action preload; hosted pages remain
unprivileged. The desktop bootstrap checks Langfuse health on localhost port 15510 and
starts an unavailable Docker stack through the existing evaluation launcher.
A failed attempt reports recovery instructions and continues ChatTFT startup.
Quitting Electron leaves the Docker stack running. See the
[desktop guide](../../../docs/desktop.md) for controls and setup.

### Desktop database workspace

Electron's Database tab hosts CloudBeaver Community in its own sandboxed,
persistent browser session alongside ChatTFT and Langfuse. This desktop-only
view connects to a separately started loopback Docker service at port 8979;
CloudBeaver owns its login, saved connections, and direct database operations.
Each external view loads lazily and retains its state while hidden, with an
independent loading deadline and Retry screen. No React routes, FastAPI APIs,
assistant tools, or RDS configuration imports participate. See
[Desktop database setup](../apps/desktop.md#database-workspace-cloudbeaver).

### Shared video service ownership

`../desktop/video-runtime.mjs` owns one suite-local VOD backend/frontend pair,
independently of ChatTFT. VOD Review and Wisps have separate persistent views
on frontend port 5174; Wisps loads `/wisp_classifier`. Occupied ports fail,
including compatible servers from original checkouts. A shared readiness promise
coalesces tab startup and retries, and quit stops the owned pair once.
`../desktop/vod_backend.py` uses VOD's own interpreter and parent-pipe lifetime;
`../desktop/vod-frontend.mjs` uses VOD's Vite config with a same-origin API proxy.
See [suite lifecycle](../../../docs/desktop.md).

## Private composition workspace

The `/compositions` page and `/api/developer/compositions` routes share the
existing backend and are enabled by default. `[chat] composition_workbench = false` disables every workbench
endpoint and hides the Electron tab. It remains outside main navigation and tools.
Pydantic response models and strict Zod counterparts validate the fixture display,
experiment controls, family explorer, inspector, and comparison. Backend lifespan
owns a serial process worker and persistent queue. With `[chat] composition_offline = true`,
the worker also starts when the application database is unavailable; Compositions
reads its checked-in eligible-board JSON and keeps history in an automatic local
SQLite store. Other database features retain their normal availability rules.
See the [composition guide](compositions/index.md).


## Local entity images

The compositions and flowchart workspaces consume the shared local asset service in
`app/backend/src/services/assets/`. `POST /api/assets/resolve` accepts a patch,
positive `set_number`, and 1–256 `entities`, each with `kind`, `name_or_id`, and
`role`. It supports unit/portrait, item/icon, trait/icon, and augment/icon.
Augments reuse item-name lookup restricted to the set's augment list.
`GET /api/assets/catalog` lists the Flowchart sidebar's units, items, and
augments with the same fallback order; see
[Flowchart entity sidebar](../apps/flowchart.md#entity-sidebar-and-images). Results
preserve request order and contain `status`, canonical `api_name`, same-origin
`src`, `asset_patch`, and `fallback`; unavailable references have a null URL.

The service constructs the existing `TFTNameResolver.from_set()` from downloaded
catalog metadata. It does not fetch Community Dragon, query the database, or
import ingestion operations during rendering. Catalogs and manifests are cached
by their file revisions; file existence is rechecked during resolution. Invalid,
legacy metadata-less, conflicting, and failed download references are unavailable.

Use the existing downloader to prepare a bundle in this checkout:

```bash
uv run python scripts/download-assets.py --patch latest --set 17 --groups portraits items traits augments
```

Replace `17` with the displayed experiment's TFT set; use a numbered `--patch`
for exact historical images. Each download now writes `catalog.json` containing
the selected set and item resolver inputs next to its existing `manifest-*.json`
files. Rerun the command for old bundles to create that metadata; existing images
are reused without `--overwrite`. Generated files under `app/static/` are ignored
by Git and are independent of frontend builds.

Runtime lookup reads the default `app/static/cdragon` folder and `en_us` locale.
The downloader's optional custom folder/locale output is not selected by this
UI. Existing `set-17.0` directories and integer `set-17` directories are both
supported. Resolution tries available exact-patch images, then `latest`, then
numbered patches in descending numeric order, always within the requested set.
Each candidate uses its own resolver inputs. Unknown entities remain placeholders;
no cross-set name matching is attempted.

`/media/tft/` serves only contained image files, with conditional ETag/Last-Modified
responses and `Cache-Control: no-cache`. URL-derived filenames can be overwritten,
so they are not advertised as immutable. Missing images and metadata requests
return 404 even with an HTML Accept header; they never return the SPA shell.
Vite proxies `/media` to FastAPI alongside `/api` and `/static`. Browser and
Electron use the same paths and components.

The frontend's `assets/EntityImages.jsx` components resolve deduplicated batches
and cache lookup results for a mounted view's patch/set. Navigating between
entities reuses those lookups; switching context disposes stale requests. Reload
the page after downloading or replacing a bundle to refresh browser lookup state.
Image transfer failures preserve labels and show the same unavailable-image note.


## Flowchart document and worker ownership

The standalone Flowchart canvas uses `flowchart/document.js` as its canonical
validated command/history layer. `projection.js` derives React Flow parent/child
nodes and collapsed boundary connections from that document; hiding or dimming
objects never changes the saved graph. `TextField.jsx` keeps edit drafts local
until commit. Revision-checked autosave receives complete canonical documents,
including undo/redo results, and ignores initial loading and DOM measurements.

`routing.worker.js` runs a sparse orthogonal visibility graph and A* with
obstacle, turn, sharing and crossing costs. `layout.worker.js` uses ELK's native
worker dispatcher; a distinct fixed-side port per connection avoids hyperedge
merger recursion on large cyclic diagrams. Worker snapshots/generations and
termination prevent superseded jobs from replacing newer edits. The pinned
`elkjs` dependency stays in the standalone Flowchart/worker bundle.

Containers, relative child geometry, locks, waypoints and label offsets persist
in `flowchart.v2` JSON on the existing tables/routes. Backend and frontend
validate containment, connection semantics, finite geometry and routing bounds.
V1 reads normalize in memory without storage writes. Collapse and named focus
views are personal localStorage state keyed by source and workspace. Clipboard
uses browser events and validated fragments, keeping desktop renderers
unprivileged. See [Flowchart commands and compatibility](../apps/flowchart.md).
