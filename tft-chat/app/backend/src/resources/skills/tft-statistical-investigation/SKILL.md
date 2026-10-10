---
name: tft-statistical-investigation
description: Plan a focused TFT investigation around the exact question, observed population, comparison, available controls, relevant metrics, and a stopping condition. Use before multi-step database work, ambiguous comparisons, conditional recommendations, or investigations where the correct cohort is not already explicit. Do not use for a single straightforward lookup with an obvious population and metric.
---

# Query Planning Framework

Before running database queries, internally identify these fields. The plan guides the investigation; the user-facing answer should lead with the conclusion.

1. **Decision being analyzed**: What action or judgment is being made?
2. **Available context**: Which requested conditions are actually observable in the supplied context and exposed tools?
3. **Primary population**: Which boards satisfy the user's exact unit, star, item, trait, and composition constraints?
4. **Comparison baseline**: For a comparison or performance claim, which relevant alternative should be compared?
5. **Controls**: Which observable differences could materially change this answer?
6. **Metrics**: Choose the measures that answer the question, plus their board samples. Frequency, average placement, top-four rate, and win rate answer different questions; do not collect every metric by default.
7. **Stopping condition**: What evidence is sufficient, and what unavailable relationship or suppressed sample would prevent answering the requested comparison?

Use only tools exposed to the executing assistant. Make a follow-up query when it can resolve a material ambiguity or test a plausible explanation for the first result. Do not query every tool family or append another investigation merely to complete a checklist.

## Define what the filters actually measure

Preserve the user's constraints. Inspect observed loadouts before defining AP/AD builds, main tanks, carries, or split investment. A single named item is evidence for that item subset, not an exhaustive build class. Keep mixed and unclassified builds visible when they affect coverage.

Unit presence alone cannot define a main tank or carry. Use recorded investment, such as completed-item count, relevant held items, and upgrades, as an explicit role proxy. Check competing invested units when the distinction matters. Final-board data cannot establish positioning, damage taken, or player intent; if the needed proxy cannot be expressed, state that limit instead of treating presence as the requested role.

When an exact build or comparison has no reportable sample, verify the constraint and stop with a concise limitation. Do not replace it with generic unit averages, a different item recipe, or a long investigation of surrounding boards. A broader comparison is useful only when it still answers a stated part of the question and its narrower evidential meaning is clear.

## Baselines Matter

Use a relevant baseline for comparative performance claims. A descriptive count or structural pattern does not need an unrelated performance comparison.

Weak baseline:

* “This item averages 4.05, so it is good.”

Useful baselines:

* Whole population baseline.
* Same comp family baseline.
* Same item holder baseline.
* Same level/stage baseline.
* Same star-level baseline.
* Same HP/economy bracket baseline.
* Same contesting level baseline.

Use these only when the tools expose the relevant dimensions. Do not invent stage, economy, contesting, or decision-time information from final-board snapshots. Retain the effective scope and any decisive limitation in the answer once, with supporting numbers in a compact table or available evidence display.
