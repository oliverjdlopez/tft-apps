---
name: tft-meta-analysis
description: Analyze TFT meta rankings, trends, compositions, units, traits, play rates, and statistically strong or weak lines from the local match store. Use for strongest, weakest, ranking, meta, trend, composition, unit, or trait questions requiring broad descriptive cuts. Report sample sizes, separate performance from popularity, and avoid unsupported timing or causal claims.
---

# TFT Meta Analysis

Use the local match data, never remembered tier lists, for current-meta claims.

1. Resolve all user-facing unit, item, and trait names together with `resolve_tft_names` before filtering.
2. Use the matching `rank_*` tool for rankings and `query_cohort` for supported descriptive groupings.
3. Read `context`, `page`, and structured `warnings` before interpreting results. Include sample size with every performance metric and treat lower average placement as better.
4. Separate performance from play rate. Call low-sample outliers promising or noisy, not definitively best.
5. Describe only relationships supported by final-board data. Do not infer stage timing, rolldown decisions, or causality from correlation.

Lead with the strongest defensible read, then the numbers and any limitation that changes the conclusion.
