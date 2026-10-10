---
name: tft-statistical-interpretation
description: Interpret TFT statistics as conditional decision-context evidence using explicit populations, metrics, baselines, sample sizes, uncertainty, correlation limits, and calibrated conclusions. Use for statistical claims, rankings, deltas, small-sample results, apparently surprising performance, or any request that could overstate what aggregate final-board data proves. Apply broadly to quantitative analysis; do not use alone when a more specific query-design or recommendation workflow is required.
---

# TFT Statistics Analysis Skill

## Core Operating Principle

TFT data is conditional. A statistic is only meaningful after understanding the situation that produced it.

Consider internally when relevant to the question:

1. **What population is this statistic drawn from?**
2. **What decision was available to the player at that point?**
3. **What hidden filters or survivorship effects may be present?**
4. **Is the observed result caused by the object itself, or by the conditions under which it is usually selected?**
5. **Which observed differences in itemization, star level, or board context could change the conclusion, and which can the tools actually control?**

Treat final-board statistics as observations of completed boards. They may help evaluate a decision, but they do not record every decision context or establish which options were available earlier.

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
* Rare capped board or niche interaction: a reportable smaller sample may support a tentative observation, but never bypass the tool's minimum sample or suppression rules.
* Exploratory hypothesis: low samples can generate questions, not final conclusions.

When sample size changes the conclusion, say so once beside the result. A suppressed or missing estimate is unavailable evidence, not zero or evidence that a build is bad. If the exact requested comparison is unavailable, explain that directly without substituting a different comparison.



## Avoiding Common Statistical Pitfalls


### Correlation

Artifacts, Radiants, and Emblems are often are correlated with other factors, which may influence their statistical performance. One example there are several augments which offer artifact items. Thus, if an artifact items is offered by a very good augment, that is a bias in favor of that artifact item, and vice versa. 

### Survivorship Bias

Conditioning on a completed high-investment board selects players who reached that board.

A capped board with excellent stats does not establish how reliably a player can reach it. Players who failed to reach it fall outside that selected cohort even if their final boards exist elsewhere in the store.

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
- Unit presence does not establish a main-tank or carry role. Use observed item investment and upgrades as a disclosed proxy; item count alone does not prove combat role. A single AP or AD item likewise does not classify the whole build or cover all builds of that type.
- A high-performing item may be a proxy for high-roll boards, player intent, or survivorship. Comparable samples reduce, but do not eliminate, that uncertainty.

## Present the finding

Apply these checks internally and expose only the evidence and limitations that affect the answer. Lead with the practical conclusion or the specific reason it remains unresolved. Assume an intermediate player; explain a statistical distinction only when it changes their reading of the result.

Put supporting numbers and board samples in one compact table or an available evidence display when comparing several values. Select the relevant metric columns rather than repeating average placement, top-four rate, win rate, and deltas in every paragraph. Do not restate the same figures in prose, repeat generic correlation caveats, or append a follow-up offer by default. End when the question is answered.

