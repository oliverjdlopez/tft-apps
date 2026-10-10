# Assistant workspace

Developer → Specs is the workspace for **edit → save draft → try → compare →
apply**. Repository files define application behavior; Langfuse owns datasets,
scored experiments, traces, and detailed comparisons. Creating, renaming, and
retiring assistants remain [CLI operations](assistant-specs.md).

Select an existing assistant. Edit `system.md`, `agent.json`, and optional
`task.md` in file tabs. Configuration and task files can be added or removed;
`system.md` is required. The summary derives model, reasoning, tools, handoffs,
repository context, and skill access from the complete draft. Active instructions
and configuration are shown separately.

## Saved revisions

**Save draft** writes only to this checkout's ignored
`.runtime/assistant-workspace/workspace.sqlite3`. Each save appends an immutable
revision with complete editable file contents, content hash, starting source and
runtime identities, validation, and provenance. One editable head exists per
assistant. Invalid drafts can be saved and corrected; Try and Apply require a
valid whole graph. Unsaved editor changes must be saved before either action.

Revisions, trial results, experiment receipts, and apply/discard history survive
browser and backend restarts. Apply or Discard closes the editable head while
retaining history. Inspect shows a revision's exact files and validation. Restore
creates a new draft revision based on current definitions; after a conflict,
review current definitions and restore the old revision to intentionally rebase.

**Import from Langfuse** lists owned assistant prompts and concrete versions.
Import resolves the selected text server-side and saves a new draft with hosted
prompt provenance. It never applies automatically. Existing datasets, authored
prompts and labels, snapshots, experiments, traces, and runner history are kept.

## Active definitions and Apply

The runtime registry caches repository definitions. Specs detects repository
edits outside that snapshot. **Refresh active definitions** validates the entire
source graph and installs it explicitly. A browser reload alone does not refresh
the cached registry. Drafts remain attached to their original starting identity.

Apply first shows diffs for every editable file. Requests carry expected draft,
source, and runtime revisions. Intervening source/runtime/draft changes return
HTTP 409; the saved draft and external files are retained. A draft started from
older definitions must be intentionally restored into a new draft before Apply.

Apply parses and validates all files together in an isolated staging directory,
including identities, tools, groups, missing handoffs, cycles, model/reasoning
settings, context policy, and skill access. A checkout file lock serializes
workspace writes. The durable `apply-journal.json` records original and replacement
bytes before replacing files. Directory and file writes are fsynced. Only
`system.md`, `agent.json`, and `task.md` are replaced; additional files survive.
A complete registry snapshot is installed for new invocations. Previously
constructed graphs keep their captured definitions and callbacks.

Interrupted writes recover before specification discovery. Uncommitted operations
roll back all journaled files; committed operations finish draft/history updates.
Recovery first checks every journaled file. An external edit conflicting with both
original and replacement bytes stops recovery and retains the journal for manual
review instead of overwriting it. Symlinked sources are rejected.

## Try

Try sends one question through the saved draft's actual configured graph in a
bounded `evals.worker` subprocess. Limits are ten turns and 180 seconds, with at
most four active trials. A disconnected browser does not cancel execution. A
backend restart stops Linux trial workers through a parent-death signal and
marks queued/running trials interrupted; Retry question explicitly
starts another trial. Results belong to their original revision after later edits.

Trials require complete explicit `RDS_EVAL_HOST`, `RDS_EVAL_PORT`, `RDS_EVAL_ADMIN`,
and `RDS_EVAL_DB` coordinates. Existing eval password/IAM authentication still
applies. Captured executions cannot borrow application database coordinates.
Validation uses deterministic local model mocks and an `_test` target identity;
normal trial execution may make paid calls when the operator chooses Try.

Each run captures active and draft definitions from the same runtime snapshot.
Only the edited assistant differs. Both captures include the union of reachable
handoff targets and the context/skill selector definitions. Configuration, task
wrappers, instructions, and resolved model defaults are frozen. Resource selection,
request-specific instruction callbacks, typed invocation context, activity hooks,
and evidence retention follow the application pipeline. Each assistant's configured
context and skill access applies at rendering. Draft registries never replace the
global registry during execution.

Trials bypass Langfuse instrumentation and tracing setup and work without its
credentials or service. Saved results include actual assembled instructions,
actual model settings, resource hashes, tool/handoff traces, usage, database name,
set number, and source provenance. Failed generations retain their assembled
instructions and invocation activity. Preparation and actual execution each record
source identity so later code changes remain distinguishable. Freezing definitions does not freeze executable tool code,
resource files, or database contents; those boundaries remain visible in receipts.

## Experiments

Run experiment reads registered live assistant datasets through the backend's
authenticated connection to this checkout's `evals/langfuse/.runtime/runner.sock`.
Credentials remain server-side. Only workflows reaching the edited assistant in
the active or draft graph are offered. Select a dataset, optional case IDs, and
repetitions; defaults are all active cases, one repetition, and concurrency four.

Preparation freezes dataset contents/version and native grading definitions, then
publishes required instruction copies under
`chattft/workspace/<assistant>/<specification-hash>`. Copies contain configuration
and specification identity and are pinned to concrete Langfuse versions. Authored
`baseline` labels never choose Active application definitions. See Langfuse's
[versioned prompt data model](https://langfuse.com/docs/prompt-management/data-model).

The comparison submits **Active** and **Draft** variants to the existing durable
queue, subprocess execution, grading, reconciliation, and artifact machinery.
Receipts retain revision/content identities, active/draft graph hashes, dataset
version, immutable snapshot identity, and job/submission identities. Workspace
snapshot blobs do not replace the dataset's registered authoring/routing snapshot.

A persistent browser/backend/runner submission identifier prevents duplicate jobs
after repeated clicks or an uncertain HTTP response. Queue insertion and its runner
receipt commit in one SQLite transaction. Failed preparation is saved and never
falls back to a baseline. An uncertain reply is retried with the same identifier;
interrupted preparation requires an explicit new submission. Results show queued,
running, awaiting-scores, completed, failed, or interrupted state and experiment
links. Earlier results remain tied to their saved revisions. Applying is allowed
after structural validation regardless of experiments or their outcome.

Fresh native Langfuse assistant experiments also capture current repository
configuration by default. Explicit historical prompt overrides and replay keep
working. The optional `execution.version = 1` snapshot section carries graphs,
managed prompt references, and lineage; schema-version 1/2/3 bundles without this
section remain readable. Startup updates only the exact owned legacy webhook
default; customized payloads and endpoints remain unchanged. `sync-langfuse`
continues to create missing authored prompts, without synchronizing existing edits.

If Langfuse or the runner is unavailable, Specs explains how to start it with
`python -m evals up`. Editing, saving, validating, Try, restore, discard, and Apply
remain usable independently.

## API and validation

`GET /api/specs` lists assistants. Existing document reads remain available;
`PUT /api/specs/documents/{id}` returns HTTP 410 with migration guidance.
`GET /api/specs/assistants/{name}` returns typed active/draft state, source drift,
validation, diffs, history, and receipts. Mutation endpoints under that assistant
are `draft`, `validate`, `apply`, `discard`, `restore`, `trials`, `experiments`, and
`import`. Each takes expected source, active, and draft revisions. `history`,
`datasets`, and `prompts` are reads. `/api/specs/refresh` takes expected source and
active identities. `/api/specs/runs/{id}` refreshes saved results without changing
the editor's files. See the generated FastAPI `/docs` for typed request/response
schemas. Store ownership is `services/assistant_workspace/`; graph capture and
execution are `domain/assistants/capture.py` and `execution.py`.

Run focused offline checks from the ChatTFT root:

```bash
.venv/bin/python -m pytest -q tests/test_spec_service.py tests/test_workspace_trials.py \
  evals/langfuse/tests/test_assistant_workspace.py
.venv/bin/python -m evals validate
cd app/frontend
npm test
npm run build
```

The real-subprocess acceptance test uses a local HTTP model mock, captured handoffs
and context tools, and a configured `assistant_workspace_test` database identity;
it does not connect to PostgreSQL or make paid calls. Live Langfuse grading and
real database-backed tools require separate configured-service verification.

## Checkout verification (2026-10-10)

The focused backend compatibility run passed 235 tests. Subsequent focused
acceptance checks passed 58 tests, including successful/failed real SDK subprocess
execution against the local model mock and owned-webhook migration. The frontend
suite passed 139 tests and the production build passed. Chromium exercised draft
save/reload, optional files, trial receipts, comparison links, diffs/Apply, import,
source conflicts, refresh, and restore against disposable specifications and
deterministic optional-service replies. The final built editor retained its full
prompt-editing height. All 78 historical snapshot files passed hash/schema loads,
and the deterministic offline fixture passed. Validation-created snapshot/catalog
changes were removed so authored catalogue content remains unchanged.

The broader Python suite did not collect fully: the optional Compositions NumPy
dependency is absent, and the existing `test_assistant_access.py` imports retired
registry APIs. The required offline validator reaches the existing `exact_unit`
missing-corpus-gold failure. A separate historical migration test still fails on
its `comp-expert` dataset mapping; the other 18 natural-workspace checks passed.
No live Langfuse grading, real PostgreSQL tool execution, paid evaluations,
ingestion, or projection rebuilds were used for these checks.
