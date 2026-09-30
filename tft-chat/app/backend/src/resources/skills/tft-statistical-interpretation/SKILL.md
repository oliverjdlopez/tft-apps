---
name: tft-statistical-interpretation
description: Interpret TFT statistics as conditional decision-context evidence using explicit populations, metrics, baselines, sample sizes, uncertainty, correlation limits, and calibrated conclusions. Use for statistical claims, rankings, deltas, small-sample results, apparently surprising performance, or any request that could overstate what aggregate final-board data proves. Apply broadly to quantitative analysis; do not use alone when a more specific query-design or recommendation workflow is required.
---

# TFT Statistics Analysis Skill

## Core Operating Principle

TFT data is conditional. A statistic is only meaningful after understanding the situation that produced it.

Always ask:

1. **What population is this statistic drawn from?**
2. **What decision was available to the player at that point?**
3. **What hidden filters or survivorship effects may be present?**
4. **Is the observed result caused by the object itself, or by the conditions under which it is usually selected?**
5. **Would this finding still hold after controlling for patch, rank, stage, placement, itemization, star level, board state, economy, and contesting?**

A TFT database should be treated as a record of **decision contexts**, not merely a leaderboard of game objects.

### Delta / Lift

Prefer relative comparisons over isolated values.

Examples:

* This item averages 4.40 on the unit overall, but 3.95 when paired with two specific complementary items.
* This comp averages 4.05 uncontested but 4.80 when two or more players contest it.

### Sample Size

Never treat low-sample stats as equivalent to high-sample stats.

Use sample size thresholds appropriate to the question:

* Broad meta trend: needs large samples.
* Common augment/item/unit comparison: moderate to large samples.
* Rare capped board or niche interaction: smaller samples may be acceptable, but confidence should be lower.
* Exploratory hypothesis: low samples can generate questions, not final conclusions.

When sample size is low, say so clearly.



## Avoiding Common Statistical Pitfalls


### Correlation

Artifacts, Radiants, and Emblems are often are correlated with other factors, which may influence their statistical performance. One example there are several augments which offer artifact items. Thus, if an artifact items is offered by a very good augment, that is a bias in favor of that artifact item, and vice versa. 

### Survivorship Bias

Final-board stats only include players who survived long enough to make those boards.

A capped board with excellent stats may not be a good line to force because failed attempts are missing or undercounted.

### Selection Bias

Players choose options when they already fit their spot.

An augment, item, or unit may look strong because good players take it only when conditions are favorable.


### Confounding

A variable may appear strong because it is correlated with another stronger variable.

To reduce confounding:

* Control for obvious related variables.
* Compare within comp families.
* Use matched contexts where possible.
* Report uncertainty when controls are unavailable.

## Understanding Evidence Limits
Board counts are necessary context for headline metrics. Other important limits include:

- `boards` is the distinct-board outcome sample; `holds` counts item instances. Do not use `holds` as the denominator for placement, top-four, or win rate.
- Average placement is better when lower, and 4.5 is the lobby baseline.
- Final-board data does not reveal item acquisition order, component availability, slam timing, roll timing, or the early-game plan. It therefore cannot establish early-slam advice or causation.
- A board-presence comparison does not bind an item to a unit. An item-holder row supports allocation association.
- A high-performing item may be a proxy for high-roll boards, player intent, or survivorship. Comparable samples reduce, but do not eliminate, that uncertainty.

