---
name: set-18-reference-traits-fae-tables
description: Fae numerical mechanics, reward tables and source disagreements. Use for detailed trait calculations and rewards.
kind: trait
sets: 18
---

# Fae

Set 18 / patch 18.2 reference supplied September 20, 2026. Source revisions differ; this is not a guarantee of synchronization to 18.2b. Published disagreements and unspecified probabilities remain unresolved.

## Pixie effects

Damage, healing, and shielding attract Pixies. Each Pixie grants Fae bonuses:

| Fae count | Attack Damage and Ability Power per Pixie | Heal per Pixie |
| --- | --- | --- |
| 2 | 5% | 2.5% maximum Health |
| 4 | 8% | 4% maximum Health |

Healing triggers when Health falls below 50%. At four Fae, after seven Pixies, Golden Pixies can be attracted for gold.

## Pixie and Golden Pixie progression

| Normal Pixies | Published threshold | 2 Fae: AD/AP; heal | 4 Fae: AD/AP; heal | With Embiggen: AD/AP, 2 / 4 Fae |
| --- | --- | --- | --- | --- |
| 1 | 2,000 | 5%; 2.5% | 8%; 4% | 17.5% / 22% |
| 2 | 7,500 | 10%; 5% | 16%; 8% | 25% / 34% |
| 3 | 15,000 | 15%; 7.5% | 24%; 12% | 32.5% / 46% |
| 4 | 30,000 | 20%; 10% | 32%; 16% | 40% / 58% |
| 5 | 70,000 | 25%; 12.5% | 40%; 20% | 47.5% / 70% |
| 6 | 110,000 | 30%; 15% | 48%; 24% | 55% / 82% |
| 7 | 155,000 | 35%; 17.5% | 56%; 28% | 62.5% / 94% |

Heal values are percentages of maximum Health. Embiggen increases Pixie AD/AP by 50% and adds 10% AD/AP immediately; it leaves the listed heals unchanged.

| Golden Pixie | Published threshold | Gold |
| --- | --- | --- |
| 1 | 170,000 | 5 |
| 2 | 200,000 | 8 |
| 3 | 300,000 | 12 |
| 4 | 400,000 | 18 |
| 5 | 500,000 | 25 |
| 6 | 600,000 | 50 |
| 7 | 888,888 | 777 |

At four Fae, the seventh normal Pixie unlocks Golden Pixies. **Remaining gap:** the graphic lists thresholds but does not fully specify counter reset, over-threshold carryover, simultaneous threshold crossing, or progress retention when Fae is deactivated. Do not add or subtract these thresholds to infer those rules.
