# Composition discovery workspace

Compositions is a private developer workspace at `/compositions`, with an
independent retained Electron tab, enabled by default through
`[chat] composition_workbench = true`. Install `uv sync --extra compositions`
before running experiments. Set the workbench setting to `false` and restart
the backend to hide the tab and make every `/api/developer/compositions/*`
endpoint return 404. Offline usage defaults to `composition_offline = false`.
The workspace is absent from main web navigation and assistant tools.

## Laptop development without PostgreSQL

The complete eligible board population is frozen in
`dev/compositions/eligible-boards.json`: 192,344 Set 18 boards from patch
`18.beta`, queue 1100, captured September 23, 2026 (58.4 MB). On a laptop, set
these values in the local `chat_tft.ini` and restart the backend:

```ini
[chat]
composition_workbench = true
composition_offline = true
```

Install the normal dependencies with `uv sync --extra compositions`, build the
frontend (`cd app/frontend`, `npm ci`, `npm run build`), then launch as usual and
open `/compositions` or the desktop Compositions tab. No PostgreSQL installation,
RDS credentials, or database migration is needed for this page. The **Configured
eligible boards** source now reads the checked-in population, and its summary
identifies offline development and the export timestamp. The synthetic fixture
remains available. HDBSCAN uses its CPU fallback when the optional GPU runtime is unavailable.

Offline experiments, progress, results, and captured samples are saved automatically
in the ignored `.runtime/compositions/experiments.db` SQLite file. History, reruns,
duplicate/edit, comparison, cancellation, and full-population classification use
the same services and worker as online mode. An OS file lock gives one supervisor
ownership of the local queue; spawned workers share that local store. Offline and
online histories are separate. Changing modes requires a backend restart. The
switch applies only to Compositions; other database-backed pages still require
RDS, and the application's database availability warning remains accurate.

The JSON retains all eligible boards, including occurrence indices, repeated units,
star levels, holder-specific item slots and identities, observed traits (including
unknown measurements), levels, and separately stored placements. Shared unit and
trait catalogs reduce repeated JSON without dropping boards. `boards[i].units`
and `boards[i].traits` are zero-based catalog references. Each unit occurrence
references `unit_entities`, and its `[slot, item_index]` equipment pairs reference
`item_entities`; `placements[i]` is that board's outcome. Strict validation checks
format version, population completeness, catalog references, and unique occurrence
indices. Anonymous observation IDs are
recreated during capture. No source board/lobby keys, scope IDs, player identifiers,
credentials, fitted models, or image binaries are exported.

Refresh deliberately on a machine with a ready application database:

```bash
uv run python -m scripts.export_composition_source
```

This always reads the live ready scoped facts, even when offline mode is enabled.
It captures the entire eligible population in one read-only repeatable-read
transaction, then atomically replaces the checked-in JSON. `--output PATH` can
write a candidate export for inspection. Commit the refreshed file to transfer it
to the laptop. Source refresh in the UI resamples the current JSON; it does not
contact the database or regenerate the export. Missing or invalid JSON disables
new source captures without falling back to RDS. Existing experiments retain their
own immutable input snapshots after a JSON refresh.

## Data and display contracts

The application-facing service boundary is `services/composition_service.py`.
The FastAPI router and app lifespan call its exported operations and worker;
implementation remains organized under `services/compositions/`, with
`domain/compositions/` owning algorithm contracts and adapters.

`domain/compositions/models.py` owns immutable Pydantic v2 observation, definition,
assignment, profile, and adapter envelopes. `services/compositions/models.py` owns
HTTP and persistence contracts. The feature's `models.js` mirrors wire constraints
with strict Zod schemas, preserving snake_case and explicit nulls. `api.js` validates
responses once before rendering. Contract failures are visible errors.

A board contains unit occurrences, each with its own star level and at most three
unique item slots. Repeated champion and item identities are valid. Unit identities
use normalized fact names; items use available canonical API identities. Unknown
traits remain unknown. A family's structural pattern restates its representative
board (the HDBSCAN medoid). It is
descriptive: discovery and classification use structural distance to frozen
references and never read it, and `matches_pattern` only reports how many assigned
boards contain every unit, item state, and trait tier of the representative. The
types keep their original names (`StructuralPattern`, `defining_patterns`) because
they are part of saved results. Alternative patterns remain separate, and
representative observations do not encode positions or replace fitted membership models.

Outcomes are stored separately and never passed to adapter fitting or classification.
Family prevalence divides assigned boards by all eligible boards in the selected
population, including ambiguous and unclassified boards. Joint support evaluates
all requirements together on each assigned board. Active-source outcome metrics
below 50 known placements are suppressed; fixture outcomes use a minimum of one.
Empty, unavailable, and suppressed metrics are null. Every board counts once.

## Reproducible experiment lifecycle

The form configures standalone HDBSCAN parameters, seed, sample size
(default 2,000, capped by the full eligible source population), source, and
optional full-population classification. The workspace asks for confirmation
before starting or rerunning a discovery sample larger than 20,000 boards;
exactly 20,000 does not prompt. This also applies to duplicated saved runs and
uses the actual frozen sample size, not the current live population. Cancelling
the confirmation submits no run. Full-population classification alone does not
trigger this sample-size confirmation.
The API accepts positive sample sizes and capture selects at most the eligible
population, including when the source shrinks after the form was loaded. Saved
snapshots keep their original sampling request for reproducible reruns.
Each parameter has a question-mark help button. Clicking it opens a single
nonmodal side panel with a one-to-three-sentence explanation of the setting and
the effect of changing it; hovering does not open help. Close or Escape dismisses
the panel and restores focus to its button. Exploration and diagnostic selectors
use the same panel. Algorithm-specific explanations live in
`app/frontend/src/compositions/parameterHelp.js`, including distinct meanings for
distance, posterior, and neighbor-support thresholds; new parameters should add
an explanation there or supply a meaningful schema description.
The source summary reports readiness, patch, set, queue, and eligible count before
capture; unavailable facts disable a new active-source start. Saved snapshots remain
reusable without current source readiness. Active source requires both the scope and anonymous fact build to be ready with the
current schema version. PostgreSQL repeatable-read capture prevents mixed revisions.
Capture reads occurrence facts in batches, creates new observation references, and
never saves source board/lobby keys or raw player/match identifiers.

`composition_snapshots` contains content-addressed inputs, outcomes, selected sample,
source context, and feature revision. `composition_experiments` contains the persistent
queue, effective settings, progress, elapsed time, safe errors, frozen JSON models,
native discovery assignments, diagnostics, and classified population results.
Snapshots have no source foreign keys, so source rebuilds cannot erase saved inputs.
`composition_snapshot_summaries` caches each snapshot's small immutable fields
(context, eligible/sample counts, sampling seed and size, full-population flag) so
history, polling, and reruns never load the frozen boards, which reach hundreds of
megabytes. Summaries are written with the snapshot, and older snapshots are
backfilled on first read with database-side JSON extraction.
The explicit additive migration is `uv run python -m scripts.migrate_compositions`.
All three tables belong to `RUNTIME_MODELS`, outside published query tables and the generic
row-browser catalogue. No automatic taxonomy promotion or assistant mutation exists.

Run responses are bounded projections of the stored result: `ExperimentView.result`
carries families, settings, diagnostics, and per-population profiles with compact
assignments (observation, status, family, variation). Fitted algorithm state, native
discovery assignments, and per-candidate evidence stay in the database and reach the
browser only through the board inspection endpoint. Completed results and the frozen
board index are cached per backend process (`persistence.saved_result` and
`persistence.frozen_boards`; results are terminal and immutable, so no invalidation
is needed). Online capture reads only the database; the frozen JSON source is used
solely when `composition_offline` is enabled.

Rerun appends a new record using identical saved inputs/settings. Duplicate and edit
loads the saved input reference and settings into the form; changing HDBSCAN
matching policy yields a new result. Changing sampling seed/size requires **Refresh
source on next start**, which explicitly captures facts when Start is pressed.
Requesting full classification from a sample-only snapshot also requires refresh.
Terminal results are immutable through the service API. Algorithm versions are frozen
when queueing; a changed implementation version refuses an old queued/rerun request
rather than silently substituting new behavior. Duplicate and edit explicitly selects
the current version.

HDBSCAN is the only algorithm listed by the workspace API. Records saved by earlier
algorithm implementations remain in storage but are hidden from history and every
workspace read, comparison, cancellation, and rerun path. No data migration is needed.

One supervisor holds a PostgreSQL advisory lock and starts one owned, fresh worker
process per experiment. A persistent FIFO queue survives restart. Startup marks
unfinished running entries interrupted; queued entries remain eligible. Cancellation
is a conditional terminal-state update followed by child termination. A late worker
cannot overwrite cancellation. Shutdown terminates only its child, and an orphan
watchdog exits if the backend disappears. Child failures, including inability to spawn, become failed runs with
safe errors. The supervisor retries queue ownership after temporary database
outages without discarding saved jobs. The UI polls saved progress and offers reopening and rerunning.

## Exploration and comparison

The family explorer presents the representative structure, the boards matching it, variations,
prevalence, outcome distributions, and up to 50 examples, prioritizing representatives.
The board inspector includes assigned, ambiguous, and unclassified observations,
candidate scores, matching evidence, and rejection reasons. Sample and full-population
results are separate choices; native discovery labels remain separate diagnostics.

Comparison shows configuration differences and label-invariant membership overlap.
Overlap is available only for identical structural populations and patch/set/queue
contexts. Families are matched optimally; rejection statuses can match only the same
status. Adjusted Rand treats each rejection status as its own label, so interpret it
alongside coverage and ambiguity. Outcome separation is never a discovery objective.

The diagnostics envelope supports named table, series, tree, graph, distribution,
and text panels. Diagnostics are data, never executable frontend code. Each algorithm
owns its fitted state and has no database, HTTP, scheduling, or rendering access.

## Operational limits

This is a local experimental workbench. Capturing the active population loads the
eligible key list for seeded selection, and full-population snapshots/results are
currently JSON documents loaded in memory. Full classification processes boards in
batches but retains the result for atomic persistence; very large populations need
capacity planning. Distance discovery uses a sample-size-square matrix, so memory
and pairwise computation grow quadratically; population-sized discovery can
exhaust available memory even after confirmation. HDBSCAN frozen-reference matching uses bounded CUDA batches when the optional
`compositions-gpu` extra and a compatible GPU are available, with compiled CPU
fallback. Standalone HDBSCAN prefers cuML fitting. Full populations can still be expensive. Cancel remains available throughout.
No learned probability should be interpreted as calibrated confidence.

## Implementation and validation

```{toctree}
:maxdepth: 1

adapter
hdbscan
validation
benchmarks
```

Use `uv run --extra compositions pytest -q tests/compositions`, frontend tests/build,
and the desktop tests. `scripts/export_composition_contracts.py` regenerates shared
JSON schemas and valid/invalid fixtures consumed by both Pydantic and Zod tests.
PostgreSQL integration tests use only isolated `RDS_TEST_*` databases ending `_test`.


## Entity images

The family navigator, representative structure, matching-board counts, variations,
representative examples, and board inspector display local unit portraits, item
icons, and trait icons. Names remain visible and searchable. Board portraits are
48 pixels; inline/item/trait icons are 24 pixels. Decorative images reserve their
space and lazy-load; unavailable images use neutral placeholders.

Family summaries include a nullable `preview` containing a bounded `pattern`,
`omitted_requirements`, and `alternative_patterns`. It contains only the first
six units and traits from the first representative structure, preserving units followed by
traits, copy counts, itemization, and tier thresholds. The navigator reports
omissions and other alternatives; it never merges alternatives or infers a board.
Families without units or traits on their representative board retain their text labels.
The family title is separate: it joins the names of the representative's itemized
units (`Unitemized structure` when none held items) and is not a definition.

Images use the result's patch/set context and the shared
[local entity asset service](../web-runtime.md#local-entity-images). A compact note
identifies fallback asset patches and unavailable images. Fixture results use
same-set fallback because their patch is `fixture`; synthetic fixture names may
remain unresolved. Repeated champions and items retain their occurrence and slot
identity; asset request deduplication does not collapse displayed occurrences.

Image metadata is presentation-only. Saved observations, model fitting, analytical
keys, and persisted experiment contracts are unchanged. There is no database
migration or LLM/tool-viewer integration in this phase. Existing experiments gain
images when reopened with a compatible local bundle.

Image rendering lives in `CompositionResults.jsx`, shared by fixture and saved-run
family browsers and the board inspector. It retains the results-first layout,
shared controls, and semantic theme tokens; white trait glyphs use a neutral dark
plate so they remain legible on the application's light surfaces.

## Euclidean board distance

New distance-based experiments use Euclidean distance on the existing weighted
board feature counts. Distances begin at zero and can exceed one. New model versions preserve the interpretation
of saved Jaccard models; old thresholds are not automatically converted.
See the [adapter contract](adapter.md) for exact encoding, defaults, and version
compatibility. CPU and CUDA reference matching use the same frozen metric;
Standalone HDBSCAN prefers cuML GPU fitting, with actual hardware reported in
diagnostics and a visible CPU fallback when unavailable.
