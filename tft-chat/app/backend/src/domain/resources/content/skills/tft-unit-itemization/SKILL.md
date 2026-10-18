---
name: tft-unit-itemization
description: Analyze item allocations for a named TFT unit, including item frequency, outcome performance, holder patterns, exact loadouts, and a requested comparison such as durability-oriented versus damage-oriented allocations. Use for unit-specific itemization questions; do not use for general item rankings without a named holder.
---

# Unit Itemization Workflow

## Define the question

Identify the named unit and whether the user asks about frequency, outcome performance, holder allocation, an exact loadout, a special item family, or another explicit comparison. Preserve the user's scope. A generic itemization overview does not need transition paths or unrelated composition analysis.

Resolve newly introduced player-language unit, item, and trait names together once before named-entity lookups. Reuse the exact stored names returned for the rest of the invocation. Do not resolve category words such as item family or a requested role comparison as entity names.

## Choose evidence that answers it

- Use `rank_items` with the named unit as holder for holder-specific item results. Distinguish item frequency from outcome performance; the leaders can differ.
- Use `rank_unit_loadouts` for exact loadout questions. For a third-slot comparison, set `item_1` and `item_2` to the fixed items and `item_count=3` so the returned candidate third item is compared with both fixed items retained.
- Use `rank_units` only when same-board conditions or a unit ranking directly answers the requested comparison.
- Use a follow-up or cohort comparison only when it addresses a material ambiguity in the user's question. Do not call every delta tool or run unrelated comparisons by default.
- Read the population, row grain, sample, and structured warnings. `boards` counts board outcomes; `holds` counts item instances. Keep item-overall, holder-specific, and exact-loadout rows distinct.

## Interpret the evidence

Read `skill:tft-unit-itemization/allocation-patterns` before interpreting item allocations. It covers frequency versus performance, role evidence, item families, acquisition context, and final-board limitations. Apply those constraints to the user's requested comparison.
