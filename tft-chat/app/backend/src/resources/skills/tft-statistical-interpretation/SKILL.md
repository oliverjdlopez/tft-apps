---
name: tft-statistical-interpretation
description: Interpret TFT aggregate results with the population, metric, baseline, sample, tool warnings, and limits that matter to the user's question. Use for statistical claims, rankings, deltas, surprising results, or conclusions that could overstate what final-board data proves. Pair with a specific analysis workflow when query design is needed.
---

# Interpreting TFT Evidence

## Match the claim to the evidence

For each conclusion, check:

1. What population and row grain does the result describe?
2. Which metric answers the user's question: outcome performance, frequency, or another requested measure?
3. Is the baseline relevant and comparable?
4. What sample information, structured warnings, intervals, or suppressed comparators affect the read?
5. Is the conclusion an observed association, or does it claim cause or a prospective decision the data cannot establish?

Use only conditions and controls the tools actually support. If a relevant confounder is unavailable, state that limitation without implying it was controlled. Do not compare unlike populations or row grains as if they shared a baseline. A first row ordered by frequency is not necessarily the strongest outcome.

Final-level and final-board cuts describe achieved states; they do not recover the causal value of earlier decisions. Do not filter on placement to make a placement comparison look fair. Use a returned interval for the actual difference when available. Overlapping intervals or a difference interval containing zero do not prove equivalence.

## Sample and uncertainty

Read sample counts alongside the metric, using the denominator appropriate to that result. In particular, `boards` counts distinct-board outcome samples and `holds` counts item instances; do not use item holds as the denominator for board placement or rates. Respect the tool's reporting floor, warning, and uncertainty output. Do not apply a universal cutoff that labels a sample as solid or conclusive. If nearby results are difficult to distinguish, describe the uncertainty rather than manufacturing a winner.

## Association and coverage limits

Aggregate final-board statistics can reflect selection, survivorship, and other correlated conditions. A result may describe a useful pattern without establishing that the item, unit, trait, or composition caused it. Final-board data does not reveal item acquisition order, component availability, slam timing, roll timing, or the early-game plan; do not turn these aggregates into timing advice.

A name-only item condition in `compare_cohorts` checks board presence on any holder. Set `holder` and optionally `holder_star_level` to bind the item to a holder; separate unit and item conditions do not imply that binding. Item copy bounds count instances across matching holders on a board, not copies on one unit occurrence. Use exact-holder or loadout evidence for allocation claims, and preserve the distinction between `boards` and `holds`.

For `rank_items(holder=X)`, the `delta` baseline is boards without that exact item-on-X pair; it does not compare X holding alternative items. A full-scope ranking has no outside population for `relative_delta`.

Use supplied context or tool results for game mechanics; do not invent item effects, abilities, or current-meta explanations.
