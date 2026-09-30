---
name: set-18-reference-traits-blackthorn-tables
description: Blackthorn numerical mechanics, reward tables and source disagreements. Use for detailed trait calculations and rewards.
kind: trait
sets: 18
---

# Blackthorn

Set 18 / patch 18.2 reference supplied September 20, 2026. Source revisions differ; this is not a guarantee of synchronization to 18.2b. Published disagreements and unspecified probabilities remain unresolved.

## Sacrifice behavior and trait breakpoints

Blackthorn sacrifices the unit placed on its designated hex before combat. The sacrifice supplies team-wide Health and additional Blackthorn-only bonuses determined by the sacrificed unit's role, cost, and star level.

| Blackthorn count | Team Health | Published additional-bonus multiplier |
| --- | --- | --- |
| 2 | 175 | Base |
| 4 | 350 | 60% stronger |
| 6 | 600 | 60% stronger |

The source displays “60% stronger” at both four and six Blackthorn. This document does not replace either entry with an inferred progression.

## Published sacrifice base values

| Sacrifice role | Base bonus |
| --- | --- |
| Tank | 12 resistances |
| Attack Damage | 14% Attack Speed |
| Ability Power | 2 Mana Regen |

These base values are not complete final bonuses. The directly published sacrifice matrix follows; its displayed rounding is retained.

## Cost, role, star, and trait-count matrix

Each cell is a pair: **Tank = Health% / Armor and Magic Resist; AD = Attack Damage% / Attack Speed%; AP = Damage Amp% / Mana Regen.** The flat team Health in Blackthorn is separate. Columns identify the sacrificed unit’s star level.

| Cost | Role | 2 trait, 1★ | 2 trait, 2★ | 2 trait, 3★ | 4 trait, 1★ | 4 trait, 2★ | 4 trait, 3★ | 6 trait, 1★ | 6 trait, 2★ | 6 trait, 3★ |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Tank | 10/7 | 17/12 | 30/21 | 13/9 | 22/16 | 39/27 | 16/12 | 27/19 | 48/34 |
| 1 | AD | 14/8 | 24/14 | 42/25 | 19/11 | 31/18 | 55/32 | 23/13 | 38/22 | 67/39 |
| 1 | AP | 8/1 | 14/2 | 25/4 | 11/2 | 18/3 | 32/5 | 13/2 | 22/3 | 39/6 |
| 2 | Tank | 12/8 | 24/17 | 48/34 | 15/11 | 31/22 | 62/44 | 19/13 | 38/27 | 76/54 |
| 2 | AD | 17/10 | 34/20 | 67/39 | 22/13 | 44/25 | 87/51 | 27/16 | 54/31 | 100/63 |
| 2 | AP | 10/1 | 20/3 | 39/6 | 13/2 | 25/4 | 51/7 | 16/2 | 31/4 | 63/9 |
| 3 | Tank | 14/10 | 30/21 | 56/40 | 18/12 | 39/27 | 73/51 | 22/15 | 48/34 | 90/63 |
| 3 | AD | 19/11 | 42/25 | 79/46 | 25/15 | 55/32 | 103/60 | 31/18 | 67/39 | 127/74 |
| 3 | AP | 11/2 | 25/4 | 46/7 | 15/2 | 32/5 | 60/9 | 18/3 | 39/6 | 74/11 |
| 4 | Tank | 19/13 | 36/25 | 850/600 | 24/17 | 46/33 | 1105/780 | 30/21 | 57/40 | 1360/960 |
| 4 | AD | 26/15 | 50/29 | 1200/700 | 34/20 | 66/38 | 1560/910 | 42/25 | 81/47 | 1920/1120 |
| 4 | AP | 15/2 | 29/4 | 700/100 | 20/3 | 38/5 | 910/130 | 25/4 | 47/7 | 1120/160 |
| 5 | Tank | 24/17 | 51/36 | 1700/1200 | 31/22 | 66/47 | 2210/1560 | 38/27 | 82/58 | 2720/1920 |
| 5 | AD | 34/20 | 72/42 | 2400/1400 | 44/25 | 94/55 | 3120/1820 | 54/31 | 115/67 | 3840/2240 |
| 5 | AP | 20/3 | 42/6 | 1400/200 | 25/4 | 55/8 | 1820/260 | 31/4 | 67/10 | 2240/320 |

**Source-value cautions:** the LBB matrix uses separate 4- and 6-trait values, broadly corresponding to 30% and 60% amplification, while the tactics.tools trait text says “60% stronger” for both. The LBB 2-cost AD 3★ / 6-trait cell specifically displays 100% AD / 63% AS; it is retained as printed rather than extrapolated. No four-star sacrifice values are supplied.
