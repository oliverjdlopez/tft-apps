# Cohort Deltas

Group key: `deltas`

Source module: `app/backend/src/domain/tools/db_tools/deltas.py`

This group owns frequency-first entity breakouts within a requested anonymous
final-board cohort. It is separate from `query_cohorts`, whose tools construct
grouped cohort tables and compare explicitly defined cohorts. Delta tools do
not expose raw rows, match identifiers, player identifiers, or mutation paths.
All tools require the active anonymous fact build to be current and ready.

## Tools

- `get_cohort_unit_deltas`: unit frequency and placement deltas, optionally
  split by exact star level.
- `get_cohort_item_deltas`: item frequency and placement deltas, optionally
  split by exact holder.
- `get_cohort_trait_deltas`: active-trait frequency and placement deltas,
  optionally split by named activation medal, matching `rank_traits`.

Every tool accepts a structured `cohort` and a bounded, zero-based,
end-exclusive `range`. Results are ordered by frequency. Unit and trait rows
expose `games` and `pick_rate`; item rows expose distinct `boards`,
instance-weighted `holds`, and `pick_rate_per_board`. Outcomes remain
board-weighted.

## Delta semantics

The placement comparisons use disjoint presence and absence samples:

- `delta = avg_placement - cohort_without_entity_avg_placement`; both sides
  are inside the requested cohort.
- `relative_delta = avg_placement - entity_outside_cohort_avg_placement`; both
  sides contain the same entity grain, but only the first is inside the cohort.

Negative values are better for both placement deltas. Rows include each
comparator's average placement and board sample so callers can verify the
calculation. A row must independently meet the 50-board public floor. Each
nonempty comparator must also meet that floor; otherwise its count, average,
and corresponding delta are `null`. A thin cohort is represented by suppressed
population context and an empty result page.

## Interpretation

The cohort is the contextual shell being investigated, not the entity being
scored. If the cohort requires the entity, the within-cohort without-entity
comparator is empty and `delta` is unavailable. These are observational
final-board associations, not causal effects or proof that adding an entity
improves a board.

All cohort membership predicates compile against anonymous board facts, and
the shared read-only database boundary enforces the tool timeout and minimum
sample policy.
