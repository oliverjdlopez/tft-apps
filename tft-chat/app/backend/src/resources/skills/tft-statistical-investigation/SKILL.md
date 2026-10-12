---
name: tft-statistical-investigation
description: Plan a focused TFT data investigation around the user's decision or question, relevant population, comparison, metric, and material uncertainty. Use for multi-step analysis, ambiguous comparisons, or conditional recommendations when the needed cohort is not already clear. Do not use for a straightforward lookup with an obvious population and metric.
---

# Focused Investigation Workflow

Start by identifying the decision or question the user wants answered. Preserve their stated constraints and format. Determine the population and comparison that matter, then choose the result or metric that would resolve the question. Use a narrow default when the request supports one; ask only for missing information that could materially change the population or conclusion.

Plan only what the available structured tools can answer:

1. State the question each planned query will answer.
2. Define the population and baseline from the user's request and supported tool conditions.
3. Choose the metric and row grain that match the decision, such as performance versus frequency or an overall versus holder-specific result.
4. Note the main interpretation risk that could change the conclusion, such as an unmatched population, a suppressed comparator, a small sample, or final-board survivorship.
5. Add a follow-up only when its possible result could resolve a material ambiguity or change the conclusion.

Do not prescribe controls the tools cannot express, or assume that every useful analysis needs a complex matched cohort. Do not run an automatic validation query or a fixed set of unrelated comparisons. Stop when the question is answered as well as the evidence allows; if it cannot be answered, state the boundary and the most useful partial result.

For exact item comparisons on a unit, place holder, star, completed-item-count, fixed-item, and candidate `required_items` or `excluded_items` constraints together in that unit's `UnitCondition` in each target and baseline. Put only board-level shell conditions and level in `shared`. Different copies can satisfy the two cohort conditions on one board, so inspect the returned overlap and do not call the cohorts disjoint by assumption. If the question is whether a specific item matters within a shell, do not require that item as part of the shared shell; compare its presence and absence explicitly.

## Baselines and interpretation

A statistic needs a relevant population and comparison. Use the whole population, a requested composition shell, an exact holder, or another baseline only when it matches the user's question and is supported by the tool. Keep metrics, populations, and row grains comparable. Describe unresolved confounding rather than implying a control that was not run.

Aggregate TFT data describes observed boards. It does not reveal the player's earlier decision context, item acquisition order, round-by-round state, or cause. Distinguish an observed final-board association from advice about what to do prospectively.
