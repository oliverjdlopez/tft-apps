---
name: tft-itemization-analysis
description: Analyze TFT unit items, holders, exact completed-item combinations, carry or tank builds, item frequency, performance, flexibility, and best-in-slot signals from local board data. Use for itemization, BIS, holder, slam, loadout, carry-build, or tank-build questions. Distinguish common from strong patterns, require sample sizes, and do not infer slam timing from final boards.
---

# TFT Itemization Analysis

Answer item questions from the scoped local match sample.

1. Use the injected context pack for the stable schema and table semantics, then resolve the unit and all relevant item names together with `resolve_tft_names`.
2. Use holder rows in `item_stats` for individual items and `unit_loadout_stats` for canonical exact one-to-three-item builds (including duplicate items) on the requested unit.
3. Use structured `compare_cohorts` item conditions when an item must be bound to a holder or star level. Item-investment bounds are not cohort inputs; use supported aggregate reports when that distinction matters.
4. Always show board count alongside average placement or top-four rate. Separate common items from high-performing items.
5. Do not call a low-sample item best-in-slot or infer when it was slammed from a final board.

Give the practical item pattern first, followed by the evidence and the closest supported caveat.
