# Analysis and Filtering

Analysis reads matches already present in the Postgres match store. Ingestion
commits a normalized match → board → unit/item/trait graph. Each committed
batch appends facts, counters, and ledger rows transactionally to the configured
analysis scope. Metrics publication and full fact validation run once after the
ingestion run's batches. The ledger makes replays no-ops; analytics failures
trigger catch-up, and endless ingestion also performs a periodic recovery sweep.

The boundary is intentionally one-way:

```text
private raw graph → scoped anonymous facts → thresholded aggregates → bounded tools
```

Ingestion and maintenance commands can mutate the private layers. Model-facing
tools cannot mutate any layer and cannot expose raw rows, match/player
identifiers, scope IDs, internal counters, or timestamps.

## Scoped population

`analysis_scopes` selects one patch, queue, and TFT set and records its universe
board count and processed-match status. Exactly one scope is active. Scope rows
and identifiers are private; model-facing aggregates are filtered to that
active scope automatically.

## Stored entities

- `raw_matches`, `player_boards`, `board_units`, `unit_items`, `board_traits`,
  and patch/set-scoped `item_metadata` are private normalized backend inputs.
- `unit_stats`, `item_stats`, `trait_stats`, and `unit_loadout_stats` are scoped
  precomputed rollups used internally by bounded ranking tools. Their relations
  and private columns are not model-queryable.
- `analysis_boards`, `analysis_board_units`, `analysis_board_items`,
  `analysis_board_traits`, `analysis_board_unit_lists`, and
  `analysis_board_trait_lists` form a private anonymous board-grain layer used
  only by bounded analysis code. UUIDv5 board/lobby keys replace raw match and
  player identifiers, and are never returned by tools. The two Set 17 wide
  list tables store one integer column per canonical unit or trait: maximum
  star level for units, active tier for traits, and zero when absent.
- `analysis_fact_builds` activates that layer only after source counts,
  anonymous lobby counts, foreign keys, schema version, and processed-match
  parity validate successfully. Item fact and aggregate API identities must
  also resolve to the exact scope's metadata display name and family.
- Structured results suppress rollup rows below 50 boards.

`db.models.query_tables.QUERY_TABLE_MODELS` is an internal projection catalogue,
not an assistant-visible schema. Tool input models, result-contract models,
minimum-sample checks, and the database read-only transaction independently
enforce the model boundary.

`item_stats` persists `item_api_name` and `item_type` as internal aggregate
metadata. The bounded `rank_items` tool can filter by `item_type` without
returning either internal field.
Display names with multiple API identities in the exact patch/set metadata are
omitted from `item_stats` rather than assigned an arbitrary identity. Rebuilds
and catch-up log these exclusions while preserving the raw slots, anonymous item
facts, and name-based loadouts. Item ranking coverage can therefore be smaller
than item fact coverage; fact/source cardinality validation remains unchanged.


Ingestion may contain display names or legacy API-style names. Resolve every
user-supplied entity through `resolve_tft_names` and filter on the exact stored
name it returns.

## Metrics and weighting

- `boards` counts distinct (`match_id`, `puuid`) pairs.
- `holds` counts item instances.
- `avg_placement` is lower-is-better, with 4.5 as the lobby baseline.
- `top4_rate` is the share finishing 1–4; `win_rate` is the share finishing first.

`holds` is item-instance weighted. Item placement, top-four, and win metrics
are board-weighted: duplicate copies of one item on a board contribute once to
that outcome bucket. Use the rollups' `games`/`boards` fields as sample sizes.

## Interpretation

The data is observational and records only final boards. Item economy, board
quality, game length, and late-game survivorship can confound raw associations.
Use the structured cohort tool for supported matched-shell comparisons, report
cohort sizes, and state when the aggregate interface cannot control a relevant
confounder. Ranking tools remain discovery-oriented: their named conditions
are scalar holder/item bindings or same-board unit/trait presence, while richer
populations stay in cohort queries and deltas. Nonempty populations below 50
boards are suppressed.

A fact build becomes usable only after source counts, anonymous lobby counts,
foreign keys, schema version, processed-match parity, and exactly one unit-list
and trait-list row per anonymous board validate. If an already-processed raw
ORM row changes, its scope and fact build become dirty; ledger catch-up cannot
repair it, so a full rebuild is required. Cohort comparisons, grouped cohort
queries, deltas, and all rankings refuse to query until that anonymous fact
build is ready because ranking rows now include board-grain `delta` and
`relative_delta`; none falls back to the normalized raw graph.
