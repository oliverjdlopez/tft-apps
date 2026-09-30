# Persistence and Analytics

The persistence layer contains a private normalized match graph, explicit
patch/queue/set analysis scopes, anonymous facts, four internal aggregate
projections, and retained legacy mappings used only during migration.

## Ownership

- `db/models/` defines the ORM registry by architectural role: `raw.py` owns
  the normalized graph, `analysis.py` owns scopes, the ledger, and anonymous
  facts, `query_tables.py` owns aggregate projections, and `legacy.py` owns
  the compatibility `matches` table and retained migration mappings. The
  package `__init__.py` assembles the runtime catalogue and
  preserves the public `db.models` import surface.
- `db/session.py` resolves typed targets, manages one engine/pool per
  purpose-and-URL, initializes runtime tables and indexes lazily, mints IAM
  tokens per physical connection, and detects raw ORM mutations that invalidate
  processed analytics.
- `db/build_query_tables.py` resolves a patch/queue/set scope and implements
  catch-up, full rebuild, facts, rollups, locking, and validation state.
- `db/validation.py` checks relational-v2 state and frozen-patch publication.
- `scripts/migrate_relational_v2.py` performs the maintenance-window cutover
  and backfill for existing databases.
- `scripts/migrate_item_metadata.py` creates the patch/set item catalogue,
  backfills raw canonical identities from exact-patch Community Dragon data,
  and invalidates disposable facts and aggregates for a required rebuild.

## Runtime schema boundary

`RUNTIME_MODELS` is the runtime creation set. It contains current normalized
raw tables, analysis tables, private composition and flowchart workspace
tables, and compatibility `matches`; it intentionally
does not contain every legacy class mapped in `Base.metadata`.
`QUERY_TABLE_MODELS` groups internal aggregate projections consumed through
bounded structured tools; it does not make their relations model-queryable.

`board_units.cost` and its aggregate projections use the game's one-based shop
cost. Ingestion prefers the exact-patch Community Dragon champion cost and
falls back to normalized Riot match rarity only when static metadata is
unavailable.

`analysis_board_unit_lists` and `analysis_board_trait_lists` are private,
Set 17-specific wide facts with one row per anonymous board. Their snake-case
feature columns cover every distinct unit and trait name in the canonical
Community Dragon set entry. Unit values are the highest star level observed on
the board; trait values are the active tier. Missing and inactive features are
stored as zero. These schemas intentionally require an explicit column
migration at each TFT set boundary. `AnalysisBoard.units` and
`AnalysisBoard.traits` expose the corresponding feature rows as one-to-one ORM
relationships; each list row links back through its `board` field.

`open_db` creates missing runtime tables and indexes and performs the narrowly
safe legacy `rarity` to 1-based `cost` normalization. It does not attempt
general migrations or infer a table-name cutover. A schema containing both
`rarity` and `cost` represents a partial migration and causes startup to fail.

## Scope lifecycle

Database tools translate trait activation styles into named tiers at query
time: 0=Inactive, 1=Bronze, 2=Silver, 3=Unique, 4=Gold, 5=Prismatic;
unrecognized styles return `Unknown`. These are Riot match-payload style values,
not Community Dragon effect styles (which use 3 for Silver, 4 for Unique,
5 for Gold, and 6 for Prismatic in Set 17).
The raw and anonymous `tier_current` breakpoint indices and numeric `style`
columns remain intact, as do existing breakpoint-based aggregate projections.
Named-tier rankings, grouping, and deltas use anonymous trait facts, so no
schema migration or analytics rebuild is needed for this presentation change.

An analysis scope is identified by patch, configured queue, and one represented
TFT set. One scope is active for serving. A full rebuild replaces the complete
projection for that identity. Catch-up processes only eligible match IDs that
are absent from the processed ledger.

Incremental analytics append under a scope lock and defer metrics publication
and complete fact validation to a finalization transaction. PostgreSQL uses an
advisory transaction lock in addition to the in-process lock. Facts, counters,
and processed-ledger changes commit atomically for each processing transaction.

A mutation to already-processed raw ORM data marks the affected scope dirty.
Catch-up cannot repair that state because the ledger says those matches were
already processed; repair requires a full rebuild.

## Database targets and maintenance

Runtime app, eval, and test access uses typed RDS targets. Test databases end
in `_test` and have coordinates isolated from app and eval targets. Explicit
DSNs are accepted only by maintenance commands that make their source or
destination explicit.

`create_all` can create missing tables but cannot migrate an existing column,
constraint, or populated table. Existing-data changes use a dedicated,
validated maintenance path.

After deploying the initial Set 17 wide tables, run a full analytics rebuild to
populate one feature row of each kind for every anonymous board:

```bash
uv run chat-tft-rebuild-tables
```

The maintenance rebuild also removes physical aggregate projections that are
no longer part of `RUNTIME_MODELS` before rebuilding the current catalogue.

The rebuild command detects loopback and Unix-socket PostgreSQL targets and
skips the temporary AWS RDS resize/restore cycle for them. Remote targets keep
the configured RDS resize behavior, so local development databases do not
require AWS credentials or an RDS instance ID.

At a later set boundary, update the two feature-column catalogues and apply an
explicit schema migration before the full rebuild. Runtime `create_all` will
create a missing wide table, but it will not add or remove roster columns from
an existing table.

During full rebuilds and incremental catch-up, item display names mapped to
multiple API identities in the scope's patch/set catalogue are skipped in
`item_stats`, with a warning naming the excluded items. Detection uses the whole
catalogue, so the outcome is independent of match order or rebuild batch size.
If an alias is discovered later, the same analytics transaction removes earlier
rankings for that ambiguous name rather than retaining partial counts.
Raw item slots, anonymous item facts, display-name loadouts, unit/trait statistics,
and processed-match ledger entries remain intact. Both same-family aliases
(such as normal and augment emblem IDs) and different-family collisions follow
this policy. Other patches and sets do not affect the exclusion.
Missing item metadata and raw/metadata display-name mismatches still stop
publication; the rebuild does not infer identities or waive fact validation.
After correcting ambiguous catalogue entries, run a full rebuild to restore
those item rankings; ordinary catch-up does not revisit processed matches.

For databases created before canonical item metadata, run the explicit
maintenance migration and then rebuild analytics:

```bash
uv run python scripts/migrate_item_metadata.py
uv run chat-tft-rebuild-tables
```

The migration is rerunnable. It reports empty, current, and partial states,
records unresolved completed items as `unknown`, rejects conflicting metadata,
and clears derived item facts and aggregates whenever a rebuild is required.
Raw item rows are processed with primary-key keyset pagination and committed in
bounded batches, so the command does not load the complete item table or retain
one database transaction for the full backfill. Repeated item identities reuse
their resolved metadata within the process, and raw identity updates use bulk
execution per batch. The default batch contains 10,000 rows; operators can tune
the memory/commit tradeoff explicitly:

```bash
uv run python scripts/migrate_item_metadata.py --batch-size 25000
```

Before the first committed raw change, the migration invalidates disposable
analytics. An interrupted run is therefore safe to rerun, but bounded batch
commits are progress durability rather than a usable partial projection; the
full analytics rebuild remains required after a changing migration.

Databases whose normalized `board_units.cost` values were derived from legacy
Riot `rarity` can be audited and repaired with the one-off unit-cost command.
Dry-run is the default and does not mutate the database:

```bash
uv run python scripts/repair_unit_costs.py
```

After reviewing the exact patch/queue/set identity and reported mismatches,
stop API and ingestion writers, retain a database snapshot, and apply the raw
corrections and full analytics rebuild in one maintenance run:

```bash
uv run python scripts/repair_unit_costs.py --apply
```

The apply path commits corrected raw costs before rebuilding. It marks an
existing scope and fact build dirty first, so a failed rebuild cannot leave the
stale model-facing projection labeled ready. Unresolved static unit identities
are reported and left unchanged.

Patch publication validates the configured patch, queue, and set before
serving. A failed publication leaves the provisioned target available for
diagnosis and does not alter application configuration.

`chat-tft-download-rds` provides a one-way developer copy from the configured
application RDS database to a local PostgreSQL database. It syncs optional RDS
ingress, uses password or IAM authentication over TLS, and keeps the source
credential out of subprocess arguments. Local cleanup remains opt-in through
`--drop-existing-objects`.

## Model-facing transaction boundary

`domain.tools.db_tools.utils.run_db_tool` is the only model-facing transaction
boundary. Each tool passes one synchronous database operation directly to it;
the boundary adds call metadata and bounded diagnostics, runs the operation in
a worker thread with a fresh session, and translates database failures into
safe tool results. PostgreSQL analysis transactions use
`SET TRANSACTION READ ONLY` and a bounded database-side statement timeout. The
worker always rolls back and closes its session; if the caller is cancelled,
the shielded database work finishes independently before that cleanup occurs.
The implementation constants in `domain.tools.db_tools.utils` are authoritative
for current timeout values. Raw rows, user identifiers, scope IDs, internal
counters, and timestamps do not cross this boundary.

## Validation surfaces

```bash
uv run pytest -q tests/test_db_session.py tests/test_db_session_concurrency.py tests/test_db_insert.py
uv run pytest -q tests/test_build_query_tables.py tests/test_relational_analytics.py tests/test_cohort_facts.py
uv run pytest -q tests/test_migrate_relational_v2.py tests/test_rebuild_tables_cli.py tests/test_update_tables_cli.py
uv run pytest -q tests/test_migrate_item_metadata.py tests/test_tft_utils.py
uv run pytest -q tests/test_freeze_patch_db.py tests/test_copy_rds.py tests/test_add_analysis_indexes.py tests/test_db_stats.py
uv run pytest -q tests/test_download_rds.py
```

Database-backed cases use `RDS_TEST_*` and skip when that isolated target is
not configured or reachable. The current inventory is documented in
`new-db-models.md`; `old-vs-new-db-models.md` retains historical migration
context. Runtime model tuples, migration code, and tests remain authoritative.

## Development database benchmarks

The development-only benchmark runner measures common read paths through the
registered database tools against the configured application database. It is
sequential and read-only; it does not run assistants, HTTP routes, ingestion,
maintenance commands, or concurrent load tests.

Run the default light and heavy workloads with:

```bash
uv run chat-tft-benchmarks
```

Use `--suite light` or `--suite heavy` to select one tier, `--no-profile` for
timing-only runs, and `--list` to inspect workloads without connecting to the
database. Each run writes `summary.json`, `events.jsonl`, and worker-thread
profiles under the ignored `profiles/benchmarks/<run-id>/` directory. The summary
contains basic sample timings and the existing database-boundary acquisition,
execution, and total timings; it is an observational development report, not
a CI performance gate.

## Private flowchart workspaces

`db/models/workspaces.py` registers two tables in `RUNTIME_MODELS` through
`WORKSPACE_MODELS`:

- `chat_tft_dev_workspaces` (`DevWorkspace`): each row holds one
  player-authored `PatchWorkspace` JSON document with a unique `name` and an
  optimistic-lock `revision`.
- `chat_tft_dev_flowchart_groups` (`DevFlowchartGroup`): the Flowchart
  library. Each row holds one saved group as a `FlowchartFragment` JSON
  document, with a unique `name` and an optional `set_number`.

Both are standalone tables, so the startup `create_all` creates them and no
data migration is needed. They are excluded from published query tables and the
row-browser catalogue, and never read or mutate match data or analytics. See
[Flowchart patch workspaces](../apps/flowchart.md).

## Private composition experiments

`db/models/compositions.py` registers `composition_snapshots`,
`composition_snapshot_summaries`, and `composition_experiments` in `RUNTIME_MODELS`. These private JSON-backed tables
are excluded from published query tables and the generic row-browser catalogue.
The additive, idempotent migration is `uv run python -m scripts.migrate_compositions`;
it refuses incompatible existing columns. It does not rebuild or mutate analytics.

Snapshots capture ready occurrence facts in a repeatable-read transaction, replace
source board keys with local observation references, and retain outcomes separately.
They have no foreign keys to disposable source scopes. Effective parameters, feature
revision, frozen models, diagnostics, assignments, and result populations survive
backend restart. Terminal results are immutable through service operations. See
[composition architecture](../architecture/compositions/index.md) for queue recovery,
cancellation, sample/full-population denominators, and memory limits.
