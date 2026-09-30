---
name: tft-cohort-comparison
description: Compare TFT board variants, units, items, holders, traits, breakpoints, carries, emblems, and conditional lines against a clearly defined baseline cohort while controlling relevant star, tier, and level conditions. Use for versus questions, deltas, variant comparisons, and whether one board condition performs better than another. Do not treat final-board association as causal evidence.
---

# TFT Cohort Comparison

Use this skill when the user asks whether one board condition performs better than another.

1. Resolve every named entity in one `resolve_tft_names` call.
2. Define mutually understandable A and B cohorts. Change only the condition under study when possible.
3. Prefer `compare_cohorts` for board-level outcome effects. Use its structured unit, holder, star, and tier conditions plus top-level exact or ranged level filters when the comparison needs them. Use `rank_*` for candidate searches; individual raw rows and arbitrary relations remain unavailable.
4. Report both cohorts' board counts, average placements, top-four rates, and deltas. Lower placement is better.
5. Flag selection bias, sparse samples, and correlated board strength. A final-board association is not proof that adding the unit or item caused the result.

Start with which variant the local data favors and under exactly what cohort definition.
