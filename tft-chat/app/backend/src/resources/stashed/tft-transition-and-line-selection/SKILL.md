---
name: tft-transition-and-line-selection
description: Select realistic TFT lines and transitions from the player's current items, units, upgrades, augments, HP, gold, level, stage, contesting, tempo, and cap requirements. Use for pivot decisions, line comparisons from a specific spot, transition planning, stabilization choices, or deciding between reachable compositions. Do not use for context-free meta rankings or retrospective statistical description without a current game state.
---

# Line Selection Through Data

Line selection is the process of choosing a realistic path from the player's current spot.

A good line is not merely the best average placement comp. It is the line with the best expected outcome given:

* Current items/components.
* Current units/pairs/upgrades.
* Current augments.
* HP.
* Gold.
* Level.
* Stage.
* Lobby contesting.
* Player's ability to transition.
* Meta speed.

### Query Strategy for Line Selection

1. Identify possible lines from current components/items.
2. Identify possible lines from current units/traits.
5. Compare expected placement from similar spots.
6. Check contesting and play rate.
7. Check required cap conditions.
