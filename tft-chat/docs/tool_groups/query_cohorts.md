# Query Cohorts

Trait-condition `tier` filters and grouped `trait_tier` results use activation
names (`Bronze`, `Silver`, `Unique`, `Gold`, `Prismatic`), derived from stored
style rather than numeric breakpoint order. To select inactive traits, set
`active: false` without a tier. Unknown styles group as `Unknown`.
The separate `style` and `total_tier` filters retain their numeric meanings.
Callers that previously supplied numeric breakpoint indices to `tier` must
now supply a medal name; numeric breakpoint indices are not interchangeable
with activation style.

Group key: `query_cohorts`

Source module: `app/backend/src/domain/tools/db_tools/cohort_tools.py`

This group owns bounded analysis over anonymous final-board cohorts. Its tools
accept `FilterGroup` inputs directly and compile every populated filter as an
all-of requirement without exposing raw rows, match identifiers, player
identifiers, or mutation paths. All tools require the active anonymous fact
build to be current and ready; they return the rebuild-required error instead
of querying the normalized raw graph when those facts are unavailable.

## Tools

### `query_cohort`

Groups a bounded cohort by one to three board, unit, item, or trait dimensions.
It returns distinct boards and lobbies, outcome rates, and pick rate within the
matched cohort. Combining unit and item dimensions binds the item to its exact
holder occurrence; trait combinations mean same-board co-occurrence.
`min_sample` and `max_sample` optionally bound each grouped row by its distinct
board count; the repository's public reporting floor cannot be lowered.

Each `FilterGroup` exposes `level`, `min_level`, and `max_level` directly for
exact or inclusive final-player-level constraints. There is no nested
`BoardCondition`; other board-wide input filters are intentionally unsupported.
The result uses object-keyed `results`, interpretive `context`, structured
`warnings`, and `page = {offset, count, has_more}`. Sub-threshold population
sizes are `null` with a suppression warning.

### `compare_cohorts`

Compares placement outcomes between two board cohorts in the active analysis
scope. Entity membership is expressed only through `unit_conditions`,
`item_conditions`, and `trait_conditions`; there are no parallel `units`,
`items`, or `traits` shorthand fields. Conditions support exact unit stars,
completed-item-count bounds, item-to-holder binding, holder stars, trait tiers,
and exact or ranged player levels. It supports:

- a required `target` cohort and optional explicit `baseline`
- complement mode by omitting `baseline`; the baseline then becomes the
  complement of `target` within the shared or active scope
- a shared context applied to both cohorts
- thresholded placement histograms, average placement, top-four and win rates,
  metric-aligned effects, explicit overlap state, and structured warnings
- lobby-clustered standard errors and 95% confidence intervals when both
  cohorts have at least 50 boards and the population contains at least 30
  lobbies

`FilterGroup` is conjunctive: every condition must hold on the same anonymous
board. A unit condition containing only `name` requires one or more copies at
any star level and with any completed-item count. A name-only item condition
requires one or more copies on any holder, and a name-only trait condition
requires the trait to be active at any tier. In all three cases, omitted
optional attributes are unconstrained. For example:

```json
{
  "unit_conditions": [{"name": "TFT17_Jinx"}],
  "item_conditions": [{"name": "TFT_Item_GuinsoosRageblade"}],
  "trait_conditions": [{"name": "TFT17_DarkStar"}]
}
```

Nested `any_of` and `none_of` branches and caller-defined cohort labels are not
supported. Comparison labels are derived from the populated conditions and
include effective defaults such as `min_copies=1` or `active=true`. Results use
matching `target` and `baseline` keys. `effects` contains
target-minus-baseline estimates by metric; available clustered uncertainty is
colocated with its estimate. `context` records the effect operation and
observational interpretation.

For frequency-first entity breakouts within a cohort, use the separate
[Cohort Deltas](deltas.md) group.

## Notes

- Each board is counted once regardless of duplicate units or item copies.
- Empty comparisons report the unavailable estimate without directing the
  assistant to widen the user's filters. A missing exact-build result can be
  the answer; changing the requested population is not an automatic fallback.
- When the invocation supplies an evidence store, `query_cohort` registers its
  bounded grouped rows and `compare_cohorts` registers a two-cohort summary
  table alongside the existing histograms. See [Evidence displays](evidence.md).
- All cohort membership predicates compile against anonymous board facts; there
  is no raw-table fallback.
- Name-only conditions are the board-presence form; add condition fields only
  for attributes that should further restrict membership.
- Item conditions with holder fields bind an item to its exact unit copy.
- Separate unit and item conditions require same-board co-occurrence, not
  item-to-unit binding. Set the item condition's `holder` and optionally
  `holder_star_level` for that binding. Item copy bounds count matching item
  instances across the board, including across multiple matching holders; they
  do not require all requested copies on one unit occurrence.
- Confidence intervals describe observational associations, not causation.
- All tools use the shared read-only database boundary and bounded PostgreSQL
  statement timeout; the execution-boundary implementation is authoritative
  for its current value.
- Failures use `kind: "error"` with a stable code, message, retry policy, and
  optional timeout rather than an ad hoc top-level error string.
