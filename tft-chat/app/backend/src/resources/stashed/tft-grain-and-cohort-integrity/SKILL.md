---
name: tft-grain-and-cohort-integrity
description: Choose the correct TFT database grain, denominator, join cardinality, deduplication strategy, and comparable player-game cohort before aggregating outcomes. Use for SQL or cohort analysis involving matches, players, board snapshots, units, item holders, augments, traits, contesting, or placement metrics where row multiplication or denominator drift could distort results. Do not use as the primary workflow for interpreting already validated aggregate output.
---

# Database Query Heuristics

### Choose the Right Grain

* Use **match** grain for global patch volume or lobby context.
* Use **player-game** grain for placement outcomes.
* Use **round/board snapshot** grain for stage-specific decisions.
* Use **unit-item-holder** grain for itemization.
* Use **augment-choice** grain for augment analysis.
* Use **lobby** grain for contesting.

Avoid mixing grains accidentally. For example, joining units and items can multiply rows and distort counts unless grouped correctly.

### Count the Right Thing

Be explicit about denominators:

* Number of player-games.
* Number of matches.
* Number of boards.
* Number of augment choices.
* Number of item-holder instances.
* Number of line attempts.

For placement metrics, the denominator is usually player-games, not rows after joins.

### Deduplicate Carefully

When joining board, unit, item, trait, and augment tables, use distinct player-game identifiers when computing placement metrics.

Bad pattern:

* Counting each item row as if it were a separate game.

Good pattern:

* First identify matching player-game IDs, then aggregate placement over those unique IDs.

### Prefer Cohort Queries

For decision analysis, define a cohort of comparable player-games.
