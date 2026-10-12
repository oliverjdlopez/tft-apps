---
name: tft-unit-itemization
description: Analyze item allocations for a named TFT unit, including item frequency, outcome performance, holder patterns, exact loadouts, and a requested comparison such as durability-oriented versus damage-oriented allocations. Use for unit-specific itemization questions; do not use for general item rankings without a named holder.
---

# Unit Itemization Workflow

## Define the question

Identify the named unit and whether the user asks about frequency, outcome performance, holder allocation, an exact loadout, a special item family, or another explicit comparison. Preserve the user's scope. A generic itemization overview does not need transition paths or unrelated composition analysis.

Resolve newly introduced player-language unit, item, and trait names together once before named-entity lookups. Reuse the exact stored names returned for the rest of the invocation. Do not resolve category words such as item family or a requested role comparison as entity names.

## Choose evidence that answers it

- Use `rank_items` with the named unit as holder for holder-specific item results. Distinguish item frequency from outcome performance; the leaders can differ.
- Use `rank_unit_loadouts` for exact loadout questions. For a third-slot comparison, set `item_1` and `item_2` to the fixed items and `item_count=3` so the returned candidate third item is compared with both fixed items retained.
- Use `rank_units` only when same-board conditions or a unit ranking directly answers the requested comparison.
- Use a follow-up or cohort comparison only when it addresses a material ambiguity in the user's question. Do not call every delta tool or run unrelated comparisons by default.
- Read the population, row grain, sample, and structured warnings. `boards` counts board outcomes; `holds` counts item instances. Keep item-overall, holder-specific, and exact-loadout rows distinct.

## Interpret allocation patterns

Separate common from high-performing. “Best” or “performs best” usually asks about outcome; “most common” or “most played” asks about frequency. Use the user-requested metric and explain the denominator. Do not call an item best-in-slot from a thin or incomparable result.

Role concepts can help organize an answer when the user or supplied game reference establishes them. For example, a user may ask to compare durability-oriented and damage-oriented allocations, or distinguish a primary carry from a frontline holder. Treat those as lenses for the requested analysis, not as facts proven by item statistics. Item names and counts alone do not establish a unit's ability scaling, in-game job, or the effect of an item. Use supplied reference material for mechanics; otherwise keep the interpretation at the level of observed allocation and outcomes.

When verified context supports the role, consider the relevant tradeoff: frontline durability and cast access, a fighter's balance of survival and damage, a ranged carry's damage and uptime, or a utility holder's access to a useful cast or application. Use that lens to identify a comparison that matters; it is not a reason to run every item or trait query.

Craftable items, Radiant items, Artifacts, Emblems, and other special families can arise in different acquisition contexts. Compare them only when the user asks or when the family is part of the stated scope and the tool can identify it. Do not infer an item's family from its name, placement, holder, or rarity.

Final-board results show association among completed boards. They do not establish that an item caused a placement result, that it was acquired early, or that an itemization was available at a particular decision point. Separate the observed pattern from any prospective recommendation and state the data boundary when it affects the answer.
