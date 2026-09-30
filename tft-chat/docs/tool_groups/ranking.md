# Ranking Tools

Group key: `ranking`

Source module: `app/backend/src/domain/tools/db_tools/ranking_tools.py`

This group is the Pythonic default for match-store discovery and ordinary
analysis. Its typed, bounded functions return deterministic ranking pages.

## Tools

- `resolve_tft_names` fuzzily resolves player-language names to exact stored
  unit, item, and trait identifiers. Call it once before filtering a ranking
  by named entities.
- `rank_units`
- `rank_items`
- `rank_traits`
- `rank_unit_loadouts`

Use `rank_*` for top, best, list, range, sorted, and single-entity requests.
Apply the relevant exact entity filters and set a small `range` for a focused
lookup.

## Shared behavior

- Every entity argument is an exact stored name and uses an equality predicate.
  Only `resolve_tft_names` performs fuzzy matching.
- `min_sample` and `max_sample` directly bound the contributing games or boards
  for each ranking row. The repository's public reporting floor still applies
  when `min_sample` is omitted or lower than that floor.
- `rank_items.item_type` restricts item-overall and holder rankings to one
  canonical family such as `artifact`, `radiant`, or `support`.
- `sort_direction="auto"` ranks average placement ascending and other metrics
  descending; callers can explicitly request either direction.
- Ranking conditions accept one exact stored name per argument and never expose
  the cohort DSL or list-valued entity filters.
- `rank_items.holder` restricts item rows to instances held by that unit.
- `rank_units.item` restricts each unit row to occurrences where that same unit
  holds the item; `rank_units.trait` requires the active trait on the same board.
- `rank_traits.unit` restricts trait rows to boards containing the unit. The unit
  need not contribute to the ranked trait.
- `rank_traits.tier` accepts medal names: `Bronze`, `Silver`, `Unique`, `Gold`,
  or `Prismatic`. Detailed rows group by the stored activation style, not the
  breakpoint index; multiple breakpoints with the same medal form one bucket.
  Across-tier rows return `tier: "All"`. Inactive traits remain excluded.
- `rank_unit_loadouts.item_1` and optional `item_2` match distinct loadout slots
  without order sensitivity; `trait` restricts them to boards where the trait
  is active. Duplicate item values require duplicate copies in the loadout.
- Rich, multi-condition populations remain the responsibility of grouped and
  comparison tools in `query_cohorts`; cohort-relative entity breakouts belong
  to the separate `deltas` group.
- `range` is a zero-based, end-exclusive two-integer slice. It defaults to
  `[0, 10]`, permits at most 100 rows, and naturally truncates at the end of
  the matching table.
- Rollup rows are the default. `group_by_star_level`, `group_by_tier`, and
  `group_by_holder` expose detailed buckets when requested.
- Every ranking row adds `delta` and `relative_delta` to its ordinary outcome
  and frequency metrics. `delta` is the row's average placement minus the
  average on boards in the same ranking population without that entity grain.
  `relative_delta` is the row's average placement inside the ranking population
  minus the same entity grain's average outside that population. Negative values
  are better. A comparator below the reporting floor, or the absent outside
  population of an unconditioned full-scope ranking, produces `null`.
- Results use `kind: "table"`, object-keyed `results`, interpretive `context`,
  structured `warnings`, and `page = {offset, count, has_more}`. They never
  exceed 100 rows per call and suppress rows representing fewer than 50 boards.
- `resolve_tft_names` uses `kind: "resolution"` with bounded candidate
  `results`. Candidate counts below 50 are `null` and marked
  `count_suppressed`.
- Rankings require the current anonymous fact build so their placement
  comparisons use the same board grain as cohort deltas. Missing analysis data
  and database failures use `kind: "error"` with a stable
  code, message, retry policy, and optional timeout.
