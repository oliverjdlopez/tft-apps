---
name: tft-statistical-investigation
description: Convert a TFT question into an executable analysis plan defining the decision, available context, population, comparison baseline, controls, metrics, likely failure modes, and a validating follow-up query. Use before multi-step database work, ambiguous comparisons, conditional recommendations, or investigations where the correct cohort is not already explicit. Do not use for a single straightforward lookup with an obvious population and metric.
---

# Query Planning Framework

Before running database queries, write or internally form a plan with these fields:

1. **Decision being analyzed**: What action or judgment is being made?
2. **Available context**: Patch, rank, stage, level, HP, gold, items, augments, units, traits, lobby state.
3. **Primary population**: Which games/rounds/boards are relevant?
4. **Comparison baseline**: What should the result be compared against?
5. **Controls**: Which variables must be held constant or stratified?
6. **Metrics**: Average placement, top 4, win rate, play rate, delta, sample size, hit rate, etc.
8. **Follow-up query**: What would validate or challenge the first result?

## Baselines Matter

Every conclusion should have a baseline.

Weak baseline:

* “This item averages 4.05, so it is good.”

Better baseline:


Useful baselines:

* Whole population baseline.
* Same comp family baseline.
* Same item holder baseline.
* Same level/stage baseline.
* Same star-level baseline.
* Same HP/economy bracket baseline.
* Same contesting level baseline.
