---
name: set-18-reference-systems-shops-pools-leveling
description: Shop cost probabilities, champion pool copies, XP requirements and hit-chance assumptions. Use for leveling and reroll math; preserves the 64 versus 68 XP disagreement.
kind: reference
sets: 18
---

# Shops, champion pools, and leveling

Set 18 / patch 18.2 reference supplied September 20, 2026. Source revisions differ; this is not a guarantee of synchronization to 18.2b. Published disagreements and unspecified probabilities remain unresolved.

## Shop cost probabilities

| Player level | 1-cost | 2-cost | 3-cost | 4-cost | 5-cost |
| --- | --- | --- | --- | --- | --- |
| 3 | 75% | 25% | 0% | 0% | 0% |
| 4 | 55% | 30% | 15% | 0% | 0% |
| 5 | 45% | 33% | 20% | 2% | 0% |
| 6 | 30% | 40% | 25% | 5% | 0% |
| 7 | 16% | 30% | 43% | 10% | 1% |
| 8 | 15% | 20% | 32% | 30% | 3% |
| 9 | 10% | 17% | 25% | 33% | 15% |
| 10 | 5% | 10% | 20% | 40% | 25% |

## Champion pool sizes

| Champion cost | Distinct champions | Copies per champion |
| --- | --- | --- |
| 1 | 14 | 30 |
| 2 | 13 | 25 |
| 3 | 14 | 18 |
| 4 | 14 | 10 |
| 5 | 10 | 9 |

## XP requirements

| Level transition | LBB: XP required |
| --- | --- |
| 3 → 4 | 6 |
| 4 → 5 | 10 |
| 5 → 6 | 20 |
| 6 → 7 | 36 |
| 7 → 8 | 56 |
| 8 → 9 | 68 |
| 9 → 10 | 68 |

Published disagreement: tactics.tools' 18.2 notes give 64 XP for both 8 → 9 and 9 → 10, rather than LBB's 68. Neither value is silently substituted here.

## Reading shop odds

A cost-tier probability is not the probability of finding one particular champion. The latter also depends on how many copies of that champion and of the other champions in its tier remain available.

For a simplified fixed-pool calculation, let:

p be the probability that a unit slot selects the target's cost tier.
a be remaining target copies, and b remaining copies across that tier.
n be the number of actual unit slots inspected.
Assuming uniform selection within the remaining tier, the per-slot probability is q = p × a / b. If those probabilities remain constant and slots are modeled independently, the chance of at least one hit is 1 − (1 − q)^n.

These are mathematical assumptions, not a claim that every in-game shop process uses independent draws or an unchanged pool. A multiple-copy calculation must account for changing availability; special shops and Wisp slots require their own treatment.
