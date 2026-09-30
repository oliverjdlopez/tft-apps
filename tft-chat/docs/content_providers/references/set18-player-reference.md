<!-- User-supplied reference, imported 2026-09-20. Source claims were not independently rechecked during import. Champion-pool/XP table splice repaired using the supplied cells; no new values added. -->

# TFT player reference: systems, rewards, traits, and Wisps

Compiled and checked: September 20, 2026. Scope: Set 18 / patch 18.2, including later corrections exposed by the accepted sources. Source revisions differ; conflicts are preserved in §13. This is a dated reference, not a claim that every page is synchronized to 18.2b.

This is a consolidated reference document, not a repository implementation plan. It contains numerical tables and mechanical rules, followed by a coverage appendix identifying material that still needs to be filled in. The original sections 1–13 and Appendices A–B are retained. The upload’s preliminary chat transcript and trailing interface text are omitted. Appendix A records the result of checking each original gap.

LBB, tactics.tools, and MetaTFT are the accepted source set. The additions below come from directly reviewed LBB graphics and the public data embedded in LBB’s pages, checked against tactics.tools where readable. LBB’s own embedded Google-hosted tables are LBB material, not an additional authority. MetaTFT was checked, but its accessible pages did not supply readable evidence for the remaining gaps; no values are attributed to it. No other TFT source was used.

Values below retain their source's meaning: percentages are probabilities only when labeled as probabilities; item and champion bundles are rewards, not estimated gold equivalents. Missing probability fields have not been replaced with assumed equal odds. Actual differences between published source values are identified where they occur.

## 1. Shops, champion pools, and leveling

### 1.1 Shop cost probabilities

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

### 1.2 Champion pool sizes

| Champion cost | Distinct champions | Copies per champion |
| --- | --- | --- |
| 1 | 14 | 30 |
| 2 | 13 | 25 |
| 3 | 14 | 18 |
| 4 | 14 | 10 |
| 5 | 10 | 9 |

### 1.3 XP requirements

| Level transition | LBB: XP required |
| --- | --- |
| 3 → 4 | 6 |
| 4 → 5 | 10 |
| 5 → 6 | 20 |
| 6 → 7 | 36 |
| 7 → 8 | 56 |
| 8 → 9 | 68 |
| 9 → 10 | 68 |

Source: [LBB — shop1](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1105,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-shop1-GdSm5CmuLYn8F51O.png). Graphic updated September 16, 2026.

Published disagreement: tactics.tools' 18.2 notes give 64 XP for both 8 → 9 and 9 → 10, rather than LBB's 68. Neither value is silently substituted here.

Source: [tactics.tools — 18.2 patch notes](https://tactics.tools/info/patch-notes/18.2).

### 1.4 Reading shop odds

A cost-tier probability is not the probability of finding one particular champion. The latter also depends on how many copies of that champion and of the other champions in its tier remain available.

For a simplified fixed-pool calculation, let:

p be the probability that a unit slot selects the target's cost tier.
a be remaining target copies, and b remaining copies across that tier.
n be the number of actual unit slots inspected.
Assuming uniform selection within the remaining tier, the per-slot probability is q = p × a / b. If those probabilities remain constant and slots are modeled independently, the chance of at least one hit is 1 − (1 − q)^n.

These are mathematical assumptions, not a claim that every in-game shop process uses independent draws or an unchanged pool. A multiple-copy calculation must account for changing availability; special shops and Wisp slots require their own treatment.

### 1.5 Augment tier sequences

S = Silver, G = Gold, P = Prismatic. These are LBB’s displayed baseline sequences, before encounter-specific overrides.

| First | Second | Third | Listed sequence chance |
| --- | --- | --- | --- |
| S | S | G | 5% |
| S | S | P | 5% |
| S | G | G | 11% |
| S | G | P | 5% |
| S | P | P | 1% |
| G | S | G | 17% |
| G | S | P | 2% |
| G | G | G | 20% |
| G | G | P | 11% |
| G | P | S | 6% |
| G | P | G | 9% |
| G | P | P | 1% |
| P | S | G | 4% |
| P | S | P | 1% |
| P | G | G | 2% |
| P | G | P | 1% |
| P | P | G | 1% |
| P | P | P | 1% |

LBB separately displays these conditional branches:

| First (listed chance) | Second, conditional on first | Third, conditional on first two |
| --- | --- | --- |
| S (26%) | S 36%; G 61%; P 4% | SS: G/P 50%/50%; SG: G/P 71%/29%; SP: P 100% |
| G (65%) | S 28%; G 48%; P 24% | GS: G/P 90%/10%; GG: G/P 65%/35%; GP: S/G/P 35%/59%/6% |
| P (9%) | S 50%; G 30%; P 20% | PS: G/P 80%/20%; PG: G/P 67%/33%; PP: G/P 50%/50% |

**Source consistency flag:** sequence percentages total 103%; first-tier percentages total 100%, and the Silver second-tier branches total 101%. These are the graphic’s rounded published fields, not a reconstructed exact probability model. Do not renormalize them or derive precise conditional odds from the rounded sequence column. Encounter-conditioned distributions remain unresolved.

Source: [LBB — augments](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1519,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-augments-ZKnTn5ALgPFKkE9F.png).

### 1.6 Player damage

| Stage | Base damage |
| --- | --- |
| 1 | 0 |
| 2 | 2 |
| 3 | 6 |
| 4 | 7 |
| 5 | 10 |
| 6 | 12 |
| 7 | 17 |
| 8 | 150 |

The graphic adds one damage per surviving unit: 1/2/3/4/5/6/7/8 units add 1/2/3/4/5/6/7/8 damage. Add this to the stage base damage. The graphic does not specify exceptions for summons, clones, ties, PvE losses, or special modes; those remain unresolved rather than generalized from this table.

Source: [LBB — damage](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=935,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-damage-1EBVEFdkkM0v4XbS.png).

## 2. Encounters

### 2.1 Published encounter rows

| Encounter | LBB chance | tactics.tools chance | Effect |
| --- | --- | --- | --- |
| 2 Cost Start | 7% | 6% | Random 2-cost. |
| 3 Cost Start | 6% | 5% | Random 3-cost. |
| Cheaper Levels | 5% | 4% | Each level costs 2 less XP. |
| Completed Item Anvil | 7% | 6% | Start with one. |
| Component Anvils | 7% | 6% | Start with two. |
| Emblem Ensemble | 2% | 2% | Three random emblems. |
| Final Showdown | 7% | 6% | Final two players receive 70 gold. |
| Gold Subscription | 5% | 4% | Stage-based gold; identical amounts for everyone. |
| Golden Finale | 5% | 4% | Third augment Gold. |
| Golden Gala | 7% | 6% | All augments Gold. |
| Golden Prelude | 5% | 4% | First augment Gold. |
| Howling Abyss | 7% | 6% | Five random 1-costs. |
| Item Forge | 3% | 3% | Two completed-item anvils. |
| No Encounter | 3% | 3% | No encounter. |
| Prismatic Finisher | 5% | 4% | Last augment Prismatic. |
| Prismatic Opener | 5% | 4% | First augment Prismatic. |
| Prismatic Party | 2% | 2% | All augments Prismatic. |
| Reroll Subscription | 3% | 3% | Rerolls at stage starts. |
| Scouting Party | 5% | 4% | One extra augment reroll. |
| Upgraded Start | 7% | 6% | Start with a 2-star. |

Source: [tactics.tools — encounters](https://tactics.tools/info/portals).

Coverage update: LBB’s 20 displayed entries total **103%**, while the same entries on tactics.tools total **88%**. The discrepancy is in the published odds. Neither table establishes a verified exact 100% distribution, and no values are renormalized or assigned to an invented encounter. LBB calls Prismatic Opener/Finisher “Prismatic Prelude/Finale.” Both source columns are retained; exact current encounter probabilities remain unresolved.

Source: [LBB — encounters](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1134,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-encounters-N723M8XNgDFLzMfH.png).

### 2.2 Gold Subscription

Gold arrives at the start of each stage. LBB publishes the five rows below, each with a listed chance and stage amounts. Everyone receives the same amounts. The graphic does not explicitly define whether a row is selected once for the game or how selections across stages are coupled; that draw cadence remains unresolved.

| Listed row chance | Stage 2 | Stage 3 | Stage 4 | Stage 5 | Stage 6 | Stage 7 |
| --- | --- | --- | --- | --- | --- | --- |
| 35% | 2 | 3 | 4 | 5 | 6 | 7 |
| 25% | 4 | 6 | 8 | 10 | 12 | 14 |
| 23% | 6 | 9 | 12 | 15 | 18 | 21 |
| 15% | 1 | 1 | 2 | 2 | 3 | 3 |
| 2% | 16 | 24 | 32 | 40 | 48 | 56 |

Source: [LBB — goldsub](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=904,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-goldsub-86VdJXKVOAw64RnU.png).

### 2.3 Reroll Subscription

At the start of stages 2/3/4/5/6/7, receive respectively **4/5/6/7/8/9 free shop rerolls**. No stage-8+ extension or expiry/carryover rule is supplied by this graphic.

Source: [LBB — rerollsub](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=545,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-rerollsub-fqyx29m2OApyKzdu.png).

## 3. Loot orbs

### 3.1 Blue orbs

| Stage | Chance | Reward |
| --- | --- | --- |
| 1–3 | 31% | 3 gold; one 3-cost |
| 1–3 | 33% | Two 3-costs |
| 1–3 | 31% | Three 2-costs |
| 1–3 | 2% | Lesser Champion Duplicator; two 2-costs |
| 1–3 | 1% | Champion Duplicator; one 3-cost |
| 1–3 | 2% | 6 gold; Reforger |
| 4+ | 49% | 4 gold; one 4-cost |
| 4+ | 47% | 2 gold; two 3-costs |
| 4+ | 1% | Champion Duplicator; 3 gold |
| 4+ | 3% | 8 gold; Reforger |

### 3.2 Silver orbs

| Stage | Chance | Reward |
| --- | --- | --- |
| 1–2 | 48% | Two 1-costs |
| 1–2 | 47% | One 2-cost |
| 1–2 | 1% | 2 gold; Item Remover |
| 1–2 | 3% | 2 gold; Reforger |
| 1–2 | 1% | Lesser Champion Duplicator |
| 3+ | 49% | One 3-cost |
| 3+ | 46% | 1 gold; one 2-cost |
| 3+ | 1% | 3 gold; Item Remover |
| 3+ | 3% | 3 gold; Reforger |
| 3+ | 1% | Lesser Champion Duplicator |

### 3.3 Prismatic orbs, Stage 3 onward

| Chance | Gold | Other rewards |
| --- | --- | --- |
| 15% | 0 | Item Remover; two Artifact anvils |
| 15% | 0 | Masterwork Upgrade; Item Remover; component anvil |
| 15% | 24 | Masterwork Upgrade |
| 15% | 18 | Reforger; completed-item anvil; component anvil; Spatula |
| 10% | 25 | Item Remover; Artifact anvil |
| 15% | 10 | Radiant Lucky Item Chest |
| 15% | 18 | Reforger; completed-item anvil; component anvil; Frying Pan |

Source: [tactics.tools — loot orbs](https://tft.tools/info/set-18/tables/loot-orbs).

LBB’s orb graphic corroborates the Blue, Gray/Silver, and Prismatic rows above. “Gray” is LBB’s name for the Silver orbs in §3.2.

### 3.4 Gold orbs

| Stage | Listed chance | Reward |
| --- | --- | --- |
| 2–3 | 20% | 15 gold |
| 2–3 | 18% | Completed-item anvil |
| 2–3 | 15% | 4 gold; Spatula or Frying Pan; Reforger |
| 2–3 | 15% | 6 gold; two 4-costs |
| 2–3 | 13% | 2 gold; four 3-costs |
| 2–3 | 10% | 1 gold; Thief’s Gloves |
| 2–3 | 3% | 6 gold; Champion Duplicator |
| 2–3 | 3% | 2 gold; Champion Duplicator; Lesser Champion Duplicator |
| 2–3 | 3% | 5 gold; three 3-costs |
| 4+ | 21% | 13 gold; one 5-cost |
| 4+ | 21% | 2 gold; two component anvils |
| 4+ | 16% | 10 gold; two 4-costs |
| 4+ | 16% | 2 gold; completed-item anvil |
| 4+ | 11% | 3 gold; Thief’s Gloves |
| 4+ | 5% | 8 gold; Champion Duplicator |
| 4+ | 5% | 7 gold; two 5-costs |
| 4+ | 5% | 1 gold; component anvil; Spatula or Frying Pan; Reforger |

The stage-2–3 and stage-4+ LBB columns each total 100%. tactics.tools gives more precise stage-4+ values: 15.8% for each LBB 16% row, 10.5% for the 11% row, and 5.3% for each 5% row (21% remains 21%); those total 100%. The Spatula/Pan icon denotes alternatives; neither table divides that combined chance. Generic cost icons specify champion costs/counts, not a guarantee that multiple random champions have the same identity.

Source comparison: [tactics.tools — loot orbs](https://tft.tools/info/set-18/tables/loot-orbs).

Source: [LBB — orbs](https://www.littlebuddybot.com/tft-system-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1980,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-orbs-6Dcjz7Q9IWtpuu12.png).

## 4. Coven

### 4.1 Essence generation

Coven gains Essence from kills and losses. The first cashout is at 40 Essence; later cashouts require more.

| Coven count | Essence per kill | Essence from a loss |
| --- | --- | --- |
| 3 | 2 | 18 |
| 4 | 2 | 25 (LBB); 32 (tactics.tools) |
| 5 | 3 | 32 |
| 7 | 10 | 60 |

The source lists Camille, Caitlyn, Elise, Cassiopeia, Morgana, and Coven Lux as Coven champions.

Source: [tactics.tools — traits](https://tactics.tools/info/traits); [LBB — Coven](https://www.littlebuddybot.com/tft-trait-tables).

### 4.2 Published cashout outcomes

The following is the LBB graphic updated September 11. Percentages are displayed values; 33% and 17% rows are rounded. A champion icon ×3 denotes three copies, while an explicit ★★ denotes a two-star champion. They are not silently treated as interchangeable when bench state matters.

| Essence | Listed chance | LBB bundle |
| --- | --- | --- |
| 40 | 33% | 4 gold |
| 40 | 33% | Two 2-costs |
| 40 | 33% | Cassiopeia; Camille |
| 85 | 33% | 2 gold; random component |
| 85 | 33% | 10 gold |
| 85 | 33% | Elise; random component |
| 130 | 25% | Two random components |
| 130 | 25% | 3 gold; random completed item |
| 130 | 25% | Cassiopeia; three Elise copies; random component |
| 130 | 25% | 3 gold; three Caitlyn copies; random component |
| 185 | 25% | Completed-item anvil; random component |
| 185 | 25% | 10 gold; completed-item anvil |
| 185 | 25% | 10 gold; two random components; Reforger |
| 185 | 25% | Three Caitlyn copies; three Camille copies; completed-item anvil |
| 250 | 20% | 20 gold; two completed-item anvils |
| 250 | 20% | 5 gold; three Morgana copies; Lucky Item Chest; random completed item |
| 250 | 20% | 18 gold; two Lucky Item Chests; Reforger |
| 250 | 20% | 18 gold; Coven Lux; Lucky Item Chest; two component anvils |
| 250 | 20% | 18 gold; Artifact anvil; completed-item anvil |
| 365 | 17% | 27 gold; two random Radiant items; two Item Removers; two Reforgers |
| 365 | 17% | 22 gold; three Morgana copies; three Sentinel copies; Radiant Lucky Item Chest; Thief’s Gloves |
| 365 | 17% | 22 gold; Radiant Lucky Item Chest; two completed-item anvils; random emblem |
| 365 | 17% | 15 gold; three Kennen copies; two Radiant Thief’s Gloves; three Item Removers |
| 365 | 17% | 22 gold; Morgana; Radiant Lucky Item Chest; two Invoker emblems |
| 365 | 17% | 12 gold; three Draven copies; Tactician’s Crown; Radiant Lucky Item Chest; Golden Item Remover |
| 500 | 20% | Three random Radiant items; two completed-item anvils; three Item Removers; three Reforgers |
| 500 | 20% | Two 5-cost entries ×3 each (tactics.tools renders two two-star 5-costs); two Radiant Lucky Item Chests; two random completed items; three Item Removers |
| 500 | 20% | 20 gold; two Radiant Lucky Item Chests; two Artifact anvils; three Item Removers |
| 500 | 20% | 10 gold; two Radiant Lucky Item Chests; four random emblems; Golden Item Remover |
| 500 | 20% | 15 gold; three Kennen copies; two-star Coven Lux; Tactician’s Shield; two Radiant Lucky Item Chests |
| 650 | 33% | 30 gold; Three 5-cost entries ×3 each (tactics.tools renders three two-star 5-costs); Tactician’s Shield; three random Radiant items; Golden Item Remover |
| 650 | 33% | 10 gold; two-star Coven Lux; three Morgana copies; Tactician’s Cape; three Radiant Lucky Item Chests; Golden Item Remover |
| 650 | 33% | 40 gold; Tactician’s Crown; three random Radiant items; three Champion Duplicators; Golden Item Remover; two Reforgers |
| 800 | 50% | 100 gold; three Tactician’s Capes; six random Radiant items; Golden Item Remover |
| 800 | 50% | 100 gold; Tactician’s Shield; six random Radiant items; six Champion Duplicators |

The Draven, Radiant-chest, and Tactician’s Cape identities were cross-checked against [tactics.tools — Coven tables](https://tft.tools/info/set-18/tables/coven). LBB lists 5 gold in the 250-Essence Morgana bundle while tactics.tools’ 18.2 notes list 3. The tables are kept source-specific. General tactics.tools reward probabilities rendered as NaN% in the upload; that does not invalidate the numeric LBB probabilities now recovered.

Source: [LBB — coven1](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1891,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-coven1-yZ8gOmoEo0iX4HnY.png).

### 4.3 Explicit 18.2 reward updates

| Essence | Bundle |
| --- | --- |
| 130 | Added: 2-star Caitlyn, component, 3 gold |
| 185 | Added: completed-item anvil, 2-star Caitlyn, 2-star Camille |
| 185 | Completed-item anvil, 10 gold |
| 250 | Two completed-item anvils, 20 gold |
| 250 | 2-star Morgana, Lucky Item Chest, completed item, 3 gold |
| 250 | Two Lucky Item Chests, 18 gold |
| 250 | Lucky Item Chest, two component anvils, Coven Lux, 18 gold |
| 250 | Artifact anvil, completed-item anvil, 18 gold |

Source: [tactics.tools — 18.2 patch notes](https://tactics.tools/info/patch-notes/18.2).

The same notes add 12 gold to the 365-Essence rewards and describe its Radiant-Gloves outcome as two Radiant Thief’s Gloves, a two-star Kennen, and 15 gold. These patch-note updates are not added a second time to the already updated LBB bundles in §4.2.

These updates do not constitute the entire Coven reward pool. In particular, an added outcome does not mean that every existing outcome at that threshold was replaced.

## 5. Blackthorn

### 5.1 Sacrifice behavior and trait breakpoints

Blackthorn sacrifices the unit placed on its designated hex before combat. The sacrifice supplies team-wide Health and additional Blackthorn-only bonuses determined by the sacrificed unit's role, cost, and star level.

| Blackthorn count | Team Health | Published additional-bonus multiplier |
| --- | --- | --- |
| 2 | 175 | Base |
| 4 | 350 | 60% stronger |
| 6 | 600 | 60% stronger |

The source displays “60% stronger” at both four and six Blackthorn. This document does not replace either entry with an inferred progression.

Source: [tactics.tools — Blackthorn trait text](https://tactics.tools/info/traits).

### 5.2 Published sacrifice base values

| Sacrifice role | Base bonus |
| --- | --- |
| Tank | 12 resistances |
| Attack Damage | 14% Attack Speed |
| Ability Power | 2 Mana Regen |

Source: [tactics.tools — 18.2 patch notes](https://tactics.tools/info/patch-notes/18.2).

These base values are not complete final bonuses. The directly published sacrifice matrix follows; its displayed rounding is retained.

### 5.3 Cost, role, star, and trait-count matrix

Each cell is a pair: **Tank = Health% / Armor and Magic Resist; AD = Attack Damage% / Attack Speed%; AP = Damage Amp% / Mana Regen.** The flat team Health in §5.1 is separate. Columns identify the sacrificed unit’s star level.

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

Source: [LBB — blackthorn](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1982,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-blackthorn-KkzospVnzd4gTrq7.png).

## 6. Riftbeast

### 6.1 Trait effects

| Riftbeast count | Effect |
| --- | --- |
| 3 | Alpha Mark gives one Riftbeast its unique bonus. |
| 5 | Every three combats, the next shop is overrun. |
| 7 | At combat start and every five seconds: 5% Attack Damage, Ability Power, and Attack Speed; 5 Armor and Magic Resist; 50 Health; 1 Mana Regen. |
| 10 | Two additional team slots. |

Elder Dragon occupies two team slots and contributes two Riftbeast through Apex Predator.

Source: [tactics.tools — traits](https://tactics.tools/info/traits).

### 6.2 Unique Riftbeast bonuses

| Riftbeast | Bonus |
| --- | --- |
| Cinderling — Scarlet | Each cast grants 22% Attack Damage. |
| Pebbles — Teal | Every four seconds channeled grants 2 Mana Regen. |
| Gromp — Purple | Gains 30% Ability Power every five seconds. |
| Murkwolf — Grey | Precision and 25% critical chance, increasing to 75% with missing Health. |
| Scuttlecrab — Green | Allies falling below 50% Health restore 15% maximum Health. |
| Krug — Slate | Krug and Kruglette deaths shield allies for 8% maximum Health. |
| Mama Beak — Orange | Physical damage reduces enemy Armor by 2. |
| Brambleback — Red | Attacks apply 1% Burn and heal itself for 4% maximum Health. |
| Sentinel — Blue | Each cast grants allies 2 Mana Regen. |
| Elder Dragon | Damage executes targets below 12% Health. |

Source: [tactics.tools — Riftbeast units](https://tactics.tools/info/units).

### 6.3 Special shops

At five Riftbeasts, every third combat causes the next shop to use a preset five-unit lineup. These are **shop-level chances of at least one copy**, assuming no three-star Riftbeast is owned. They are not per-slot odds and need not sum to 100% down a column. Each cell is **chance / maximum copies in that shop**.

| Champion | Level 4 | Level 5 | Level 6 | Level 7 | Level 8 | Level 9 | Level 10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Cinderling | 67% / 2 | 66% / 2 | 64% / 2 | 59% / 2 | 31% / 3 | 21% / 3 | 9% / 1 |
| Pebbles | 67% / 2 | 66% / 2 | 64% / 2 | 59% / 2 | 31% / 3 | 21% / 3 | 9% / 1 |
| Murkwolf | 44% / 2 | 44% / 2 | 44% / 2 | 45% / 2 | 29% / 2 | 24% / 3 | 14% / 3 |
| Gromp | 56% / 1 | 56% / 2 | 55% / 2 | 55% / 2 | 51% / 2 | 45% / 2 | 14% / 2 |
| Scuttlecrab | 56% / 2 | 56% / 2 | 55% / 2 | 55% / 2 | 51% / 2 | 47% / 3 | 27% / 3 |
| Mama Beak | 33% / 1 | 34% / 2 | 39% / 2 | 52% / 2 | 52% / 2 | 53% / 2 | 64% / 3 |
| Krug | 67% / 1 | 67% / 2 | 69% / 2 | 76% / 2 | 76% / 2 | 74% / 2 | 64% / 3 |
| Sentinel | 11% / 1 | 11% / 1 | 12% / 1 | 15% / 1 | 34% / 1 | 34% / 1 | 24% / 1 |
| Brambleback | 11% / 1 | 11% / 1 | 12% / 1 | 15% / 1 | 34% / 1 | 39% / 1 | 51% / 1 |
| Elder Dragon | — | — | — | — | — | 5% / 1 | 45% / 1 |

**Remaining gap:** individual five-unit lineup weights, and the modified distribution when a three-star Riftbeast is owned, are not established by this marginal table.

Source: [LBB — riftbeast](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1502,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-riftbeast-L8Cyj8d7b6fL0V35.png).

## 7. Fae

### 7.1 Pixie effects

Damage, healing, and shielding attract Pixies. Each Pixie grants Fae bonuses:

| Fae count | Attack Damage and Ability Power per Pixie | Heal per Pixie |
| --- | --- | --- |
| 2 | 5% | 2.5% maximum Health |
| 4 | 8% | 4% maximum Health |

Healing triggers when Health falls below 50%. At four Fae, after seven Pixies, Golden Pixies can be attracted for gold.

Source: [tactics.tools — Fae](https://tactics.tools/info/traits).

### 7.2 Pixie and Golden Pixie progression

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

Source: [LBB — fae](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1475,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-fae-9tzZQEeGne1IT9Jh.png).

## 8. Lux and Avatar variants

### 8.1 Avatar selection

Owning a Lux on the board or bench changes other Avatars appearing in your shop to her trait. Her chosen trait counts twice.

Source: [tactics.tools — traits](https://tactics.tools/info/traits).

### 8.2 Shared Lux ability

On casting, allies sharing a trait with Lux receive mana; the displayed star-level values are 3 / 3 / 100. Her laser targets a line containing the most enemies. Displayed damage is 375 / 565 / 6,500, with 25% / 25% / 10% falloff per enemy hit, down to a 40% floor.

These are the displayed ability values, not a damage simulation incorporating every modifier.

Source: [tactics.tools — Lux abilities](https://tactics.tools/info/units).

### 8.3 Variant comparison

| Lux variant | Additional effect |
| --- | --- |
| Blackthorn | Stuns for one second. |
| Blossom | First target takes 10% extra damage. |
| Coven | Targets lose 8 Armor and Magic Resist for the rest of combat. |
| Elderwood | Each cast grants all allies 2.5% increased maximum Health for the rest of combat. |
| Fae | Heals the lowest-percent-Health ally for 18% of ability damage dealt. |
| Inferno | Gains 10 mana per takedown. |
| Lunar | Applies 8% Vulnerable for four seconds. |
| Primal | Gains 60% Attack Speed for six seconds after casting. |
| Solar | Deals 12% additional damage per unique 3-star champion fielded. |

Vulnerable increases damage taken.

Source: [tactics.tools — units](https://tactics.tools/info/units).

LBB’s reviewed Lux graphic agrees on the shared ability and six variant effects, but lists Inferno **8** mana per takedown, Lunar **10%** Vulnerable, and Primal **50%** Attack Speed. The tactics.tools values above remain **10 / 8% / 60%** respectively. These three source conflicts remain unresolved.

Source: [LBB — lux](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1215,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-lux-e63LewE0thiKctaA.png).

## 9. Other set-specific trait rules

### 9.1 Sprykin and the BFF

Drop a Sprykin onto the BFF to choose its rider. Melee and ranged riders change the BFF's attacks and ability.

| Sprykin count | Rider Health | Rider Attack Speed | Additional effect |
| --- | --- | --- | --- |
| 3 | 15% | 15% | — |
| 5 | 40% | 35% | LBB: 50%; tactics.tools: 100% of the BFF's ability applies to Sprykin. |
| 7 | 45% | 45% | 100% of the BFF's ability applies to Sprykin. |

Teemo's additional mushrooms

| Teemo star level | Extra-mushroom chance per cast |
| --- | --- |
| 1 | 10% |
| 2 | 12% |
| 3 | 15% |
| Mushroom | Reward |
| Red | One shop reroll |
| Green | One Tactician Health |
| Yellow | Two XP |

LBB publishes the following rider and ability values. SFF is the Small Furry Friend augment’s second BFF at 35% strength.

| Sprykin | SFF rider Health / AS | BFF melee heal: rider / other allies | SFF melee heal: rider / other Sprykin | BFF ranged AD/AP | SFF ranged AD/AP |
| --- | --- | --- | --- | --- | --- |
| 3 | 5.25% / 5.25% | 10% / 0% | 3.5% / 0% | 15% | 5.25% |
| 5 | 14% / 12.25% | 13% / 6.5% | 4.6% / 2.3% | 30% | 10.5% |
| 7 | 15.75% / 15.75% | 16% / 16% | 5.6% / 5.6% | 40% | 14% |

Melee values are maximum-Health healing; ranged values last for the rest of combat. LBB labels BFF’s extra heal recipients “other allies,” while the trait’s sharing sentence refers to Sprykin; that targeting scope and the five-Sprykin 50%/100% conflict remain flagged. The graphic supplies rider/ability bonuses, not an independent BFF base Health, Attack Damage, Armor, or Mana stat sheet.

Source: [LBB — sprykin](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1467,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-sprykin-g7YqjSzf7xKrgsdy.png).

Source: [tactics.tools — Sprykin](https://tactics.tools/info/traits).

### 9.2 Blossom

After combat, Blossom empowers Wisps. Blossom champions gain 10% maximum Health alongside these Attack Damage and Ability Power bonuses:

| Blossom count | Attack Damage and Ability Power | Wisp effect |
| --- | --- | --- |
| 3 | 12% | Upgraded Wisps |
| 5 | 30% | Wisps in every shop |
| 7 | 45% | Receive 4 gold after buying a Wisp |
| 9 | 50% | May buy two Wisps per round |
| 11 | 100% | Further Wisp empowerment |

At 11 Blossom, Wisps receive their Prismatic effects; LBB’s Prismatic-trait chart requires at least two emblems. §11.7 records all 19 Prismatic Wisp entries exposed by LBB’s database, including numerical effects where the source provides them. Three entries still use qualitative descriptions.

Source: [LBB — prismatic traits](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=566,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-prismatic-traits-6ZLIF4a8W8aTXtfj.png).

Source: [tactics.tools — Blossom](https://tactics.tools/info/traits).

### 9.3 Elderwood plants

| Elderwood count | Plant upgrade |
| --- | --- |
| 3 | Stonebark Tree and Lifebloom |
| 5 | Second Stonebark Tree; Stonebark Trees gain 200 Health |
| 7 | Deepwood Protector |
| 9 | Plants become 2-star |
| 11 | Plants become 3-star; Deepwood Protectors spawn every 7 seconds |

Plants gain 25% maximum Health and 10% Ability Power per Elderwood star level. LBB’s 11-Elderwood quest requires at least two emblems.

Source: [LBB — prismatic traits](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=566,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-prismatic-traits-6ZLIF4a8W8aTXtfj.png).

Other Elderwood interactions
Ornn accumulates Forge Power from damage blocked in player combat; generation doubles at 3-star. Reaching a requirement awards an Artifact Anvil. Exact Forge Power requirements are not included here.

After player combat, the strongest LeBlanc can copy an ally on the board. Her displayed base chances are 10% / 15% / 40%, increased by four percentage points per takedown.

Source: [tactics.tools — Elderwood](https://tactics.tools/info/traits); [unit quest text](https://tactics.tools/info/units).

### 9.4 Solar

Three Solar grants the team a 5% maximum-Health shield and 8% bonus magic damage.

| Unique 3-star champions | Additional effect |
| --- | --- |
| 1+ | Each adds 1% to the shield and bonus magic damage. |
| 3 | 15% Attack Speed; 12 Armor and Magic Resist. |
| 5 | Convert 40% of the bonus magic damage into true damage. |
| 8 | Every four seconds, a 3-star champion ascends to 4-star. |

Source: [tactics.tools — Solar](https://tactics.tools/info/traits).

### 9.5 Lunar

Lunar champions and adjacent allies gain Attack Speed and Ability Power. Lunar champions receive twice the listed base amount.

| Lunar count | Base Attack Speed | Base Ability Power |
| --- | --- | --- |
| 2 | 7% | 7% |
| 3 | 10% | 10% |
| 4 | 14% | 14% |
| 5 | 18% | 18% |

Source: [tactics.tools — Lunar](https://tactics.tools/info/traits).

### 9.6 Eclipse

Field three Solar and three Lunar. After ten seconds, Eclipse kills the lowest-Health enemy, repeating every 3.5 seconds.

### 9.7 Primal

Primal has two- and four-unit breakpoints. LBB recovers the blessing effects that did not render in tactics.tools:

| Blessing | Published effect |
| --- | --- |
| Turtle | Team restores 4% maximum Health every 4 seconds. |
| Bear | Primal damage executes enemies below 12% Health. |
| Tiger | At 6 seconds, Primal champions gain 35% Attack Speed and the team gains 15% Attack Speed. |
| Phoenix | Each 15 Primal takedowns grants a component, up to four components. |

**Remaining gap:** the graphic does not map separate numerical effects to the two/four breakpoints or explain whether Tiger’s Primal and team portions stack. No extra scaling or combined 50% value is inferred. The Beast Within augment grants an additional blessing, as stated by LBB’s augment database.

Source: [LBB — primal](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=600,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-primal-AyCPOzrTCxAFUpIR.png).

Source: [LBB — augment database](https://www.littlebuddybot.com/tft-augments).

## 10. Augment rewards and interactions

### 10.1 Call to Chaos

Each of these nine outcomes is displayed at 11.1%:

| Outcome | Reward bundle |
| --- | --- |
| Gold | 58 gold |
| Experience | 64 XP |
| Rerolls | 40 shop rerolls |
| Gloves | Three Thief's Gloves; Item Remover |
| Radiant chest | Radiant Lucky Item Chest; 8 gold; Item Remover |
| Item chests | Three Lucky Item Chests; Item Remover |
| Components | Six random components |
| Crafting | Spatula; Frying Pan; two component anvils |
| Egg | Golden Egg; completed-item anvil |

Source: [tactics.tools — Call to Chaos](https://tft.tools/info/set-18/tables/call-to-chaos).

The displayed percentages sum to 99.9% because of rounding. LBB prints 11% for each outcome and specifies that the six components are unique.

Source: [LBB — chaos](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=845,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-chaos-rtbGFGsnMS0SsBYz.png).

### 10.2 Golden Egg

The egg takes eleven turns to hatch; player-combat wins shorten the countdown by an additional turn.

Source: [tactics.tools — augments](https://tactics.tools/info/augments).

| Chance | Reward bundle |
| --- | --- |
| 15% | 88 gold; Tactician's Crown |
| 15% | Two Tactician's Crowns; Thief's Gloves; 30 gold |
| 10% | Infinity Force; Zhonya's Paradox; The Indomitable; Champion Duplicator; two Item Removers; 25 gold |
| 15% | Tactician's Crown; Radiant Thief's Gloves; Thief's Gloves; 25 gold |
| 10% | Random completed item; two random Artifacts; 10 gold; Item Remover; Tactician's Crown |
| 10% | Tactician's Crown; two Champion Duplicators; four random 5-costs; 30 gold |
| 15% | Two random Radiant items; Tactician's Crown; 10 gold |
| 10% | Infinity Edge; Jeweled Gauntlet; Striker's Flail; Tactician's Crown; Hand of Justice; Quicksilver; Item Remover; 10 gold |

Source: [tactics.tools — Golden Egg](https://tft.tools/info/set-18/tables/golden-egg).

**Accepted-source conflict:** the 10% bundle containing a random completed item, 10 gold, Remover, and Crown has **two Artifacts** in tactics.tools, but **one Artifact plus one Radiant item** in LBB’s September 11 graphic. The row above retains tactics.tools’ version; the alternative remains explicit.

Source: [LBB — goldenegg](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=807,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-goldenegg-hsDbLWlxSROGHs71.png).

### 10.3 Expedition

At round starts, consumes the rightmost benched champion until 33 gold of value has been consumed. Initially grants a 3-cost.

Source: [tactics.tools — augments](https://tactics.tools/info/augments).

The published cashout bundle is 15 gold, a component anvil, a Masterwork Upgrade, and two random 5-cost champions. LBB independently publishes this same single reward bundle. Its graphic does not label a percentage, and tactics.tools renders NaN%; no numerical probability is assigned.

Source: [LBB — expedition](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=768,h=168,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-expedition-LLdLIg35yZkpQkEz.png).

Source: [tactics.tools — Expedition](https://tft.tools/info/set-18/tables/expedition).

### 10.4 Other recovered augment rules

| Augment | Rule |
| --- | --- |
| Missed Connections | One of each 1-cost. |
| Slice of Life | Stage-based champion deliveries, ending at one 5-cost. |
| Frontline Foundation | 2-star 1-cost Tank; matching class emblem. |
| Backline Blueprint | 3-cost non-Tank; matching class emblem. |
| Blossom's Call | Wisp purchases grant Blossom champions based on Wisp cost. |
| Bonus Gift | Loot-orb openings have a 25% gray-orb chance. |
| Booster Pack / + / ++ | 12 / 18 / 26 gold of champions; includes a 3- / 4- / 5-cost, respectively. |
| Hard Commit | Emblem; matching champion and 3 gold now and each stage start. Champion cost caps at five. |
| Solo Leveling | Five combats at team size one; kill XP; two components afterward. |
| Slightly Magic Roll | One die determines the reward. |
| Magic Roll | Three-dice total determines the reward. |
| Warpath | Initially a 2-star 2-cost; chest after 80 player damage. |
| Small Furry Friend (second BFF) | Second BFF at 35% strength. |
| Loaded Dice | Luckier dice/coins; immediate die-result gold, plus one on heads. |

Source: [tactics.tools — augments](https://tactics.tools/info/augments).

### 10.5 Offer restrictions

LBB marks these entries “1 Player”: **Consuming Flora, Coven Acolyte, Dark Ritual, Expedition, Trait Ladder, and Unrivaled**. Coven Acolyte and Dark Ritual are also mutually exclusive. A per-entry one-player flag and personal incompatibility are distinct fields; the recovered flags alone do not prove a shared lobby-wide cap across two different entries.

Mutually exclusive: Trait Tree Plus and Cooking Pot.

### 10.6 Dark Ritual

| Cashout / Essence threshold | Ability Power |
| --- | --- |
| 1 / 40 | 7 |
| 2 / 85 | 15 |
| 3 / 130 | 50 |
| 4 / 185 | 75 |
| 5 / 250 | 125 |
| 6 / 365 | 200 |
| 7 / 500 | 300 |
| 8 / 650 | 400 |
| 9 / 800 | 1666 |

The first seven values are listed in the 18.2 notes; the complete threshold mapping and final two values are printed in LBB’s Coven graphic.

Source: [LBB — coven1](https://www.littlebuddybot.com/tft-trait-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1891,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-coven1-yZ8gOmoEo0iX4HnY.png).

Source: [tactics.tools — 18.2 patch notes](https://tactics.tools/info/patch-notes/18.2).

A personal incompatibility is not the same as a lobby-wide restriction. Appendix A.1 now includes every restriction row recovered from LBB’s embedded augment table. It is not an independently verified inventory of all enabled or disabled in-game augments.

### 10.7 Trait Ladder

Gain a random emblem. Complete successively larger counts of non-unique active traits in player combat; each reached rung gives its reward.

| Traits | LBB reward |
| --- | --- |
| 2 | 1 gold; Reforger |
| 3 | 3 gold |
| 4 | 6 gold |
| 5 | Random component |
| 6 | 50%: 10 gold; 50%: three 3-costs |
| 7 | 8 gold; component anvil |
| 8 | 57%: two components and Reforger; 43%: completed-item anvil |
| 9 | 2 gold; three 5-costs |
| 10 | 20 gold |
| 11 | Tactician item |
| 12 | Three 4-costs; Lucky Item Chest |
| 13 | 8 gold; four components; Item Remover |
| 14 | 10 gold; Masterwork Upgrade |

The Tactician-item type probabilities at rung 11 are not specified by LBB. The general tactics.tools table still puts that item at rung 10, 18 gold at rung 11, and omits the rung-7 component anvil. Those differences remain documented; its old rung-10 type probabilities are not reassigned to LBB’s rung 11.

Source: [LBB — traitladder](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1194,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-traitladder-0LLlTR6QxE35fUhw.png).

Source comparison: [tactics.tools — Trait Ladder](https://tft.tools/info/set-18/tables/trait-ladder).

### 10.8 Loaded Dice interactions

| Source | Stage shown | Effect with Loaded Dice |
| --- | --- | --- |
| Loaded Dice initial die | 2 | 6 guaranteed |
| Loaded Dice initial coin | 2 | Heads guaranteed |
| Coin Flip | 2 | Heads guaranteed |
| Feeling Lucky | 3 | Heads guaranteed |
| A Magic Roll | 3 | Dice total at least 14 |
| Flip Frenzy | 3/4 | First five flips are heads |
| Die Roll | 3/4 | 6 guaranteed |
| Golden Gamble | 3/4 | Heads guaranteed; Radiant Lucky Item Chest |

This establishes the listed guarantees, not the complete conditional distribution of Magic Roll totals 14–18. LBB does not give that distribution or a separate Slightly Magic Roll interaction.

Source: [LBB — loaded](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1255,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-loaded-ZEjKx9vuXiNxlwMq.png).

### 10.9 Blossom’s Call

These are possible delivered champions, not equal-probability pools.

| Stage | Wisp cost | Possible champions |
| --- | --- | --- |
| 4 | 0 | Karma, Yorick |
| 4 | 1–2 | Karma, Yorick, Yunara, Master Yi |
| 4 | 3 | Yunara, Master Yi |
| 4 | 4 | Yunara, Master Yi, Ahri, Sett |
| 4 | 5–7 | Master Yi, Ahri, Sett |
| 4 | 8+ | Master Yi, Ahri, Sett, Ashe |
| 5 | 0–1 | Karma, Yorick, Yunara, Master Yi, Ahri, Sett |
| 5 | 2–3 | Yunara, Master Yi, Ahri, Sett |
| 5 | 4 | Master Yi, Ahri, Sett |
| 5 | 5+ | Master Yi, Ahri, Sett, Ashe |
| 6 | 0–1 | Yunara, Master Yi, Ahri, Sett, Ashe |
| 6 | 2–10 | Master Yi, Ahri, Sett, Ashe |
| 6 | 11+ | Ashe |

The graphic labels Stage 6, not Stage 6+; later stages and per-champion probabilities remain unspecified.

Source: [LBB — blossom](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1171,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-blossom-ldnOIJXBDI8JonvN.png).

### 10.10 Booster Pack / + / ++

Notation: **cost★** identifies one champion by cost and star level; **×N** means N champions of that entry. Unmarked star levels are one-star. These are the packages depicted by LBB, not conversions to gold equivalents.

#### Booster Pack (Stage 2)

| Listed chance | Package |
| --- | --- |
| 13.5% | 1; 2; 3 ×3 |
| 13.5% | 1 ×2; 2 ×2; 3; 1★★ |
| 13.5% | 1 ×2; 2 ×2; 3; 3 |
| 13.5% | 1 ×3; 3 ×2; 1★★ |
| 13.5% | 1 ×2; 2 ×2; 3 ×2 |
| 13.5% | 1; 2; 3; 1★★ ×2 |
| 8% | 1; 2; 3; 2★★ |
| 8% | 1; 2; 3; 2★★ |
| 1.5% | 1; 2; 3★★ |
| 1.5% | 1 ×3; 2; 3; 4 |

#### Booster Pack+ (Stage 3)

| Listed chance | Package |
| --- | --- |
| 11% | 2 ×2; 4 ×2; 2★★ |
| 11% | 2; 3 ×2; 4; 2★★ |
| 11% | 2; 4; 1★★ ×4 |
| 11% | 1; 3 ×3; 4 ×2 |
| 11% | 2 ×2; 4 ×2; 1★★ ×2 |
| 11% | 2; 3 ×2; 4; 2★★ |
| 10% | 2; 3; 4; 1★★★ |
| 8% | 2; 3; 4; 3★★ |
| 8% | 1; 2 ×2; 4; 3★★ |
| 5% | 2 ×3; 4 ×3 |
| 4% | 3 ×3; 4; 5 |

#### Booster Pack++ (Stage 4)

| Listed chance | Package |
| --- | --- |
| 12% | 3; 5; 2★★★ |
| 12% | 1; 2; 5; 3★★; 3★★ |
| 12% | 5; 1★★; 1★★; 2★★; 3★★ |
| 12% | 4; 5; 5; 2★★; 2★★ |
| 12% | 4 ×4; 5 ×2 |
| 12% | 4 ×3; 5; 1★★; 2★★ |
| 12% | 1; 3 ×2; 5 ×2; 1★★★ |
| 4% | 3 ×2; 5 ×4 |
| 4% | 3; 5; 1★★★; 1★★★ |
| 4% | 5; 3★★; 4★★ |
| 3% | 3; 5; 2★★; 4★★ |
| 1% | 1; 3; 3; 4; 5★★ |

**Source-value flags:** duplicate-looking rows are retained because the graphic shows separate outcomes. The + probabilities sum to 101% as printed; tactics.tools prints 3% instead of 4% for its three-3-costs / 4-cost / 5-cost outcome. Several high-star depictions also differ: LBB’s + 10% row shows a three-star 1-cost, and its ++ 12% first/seventh and 4% two-1-cost rows show three-star units; tactics.tools shows two-star versions and includes an additional 2-cost in the latter row. These packages are not silently reconciled.

Source: [LBB — booster](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1548,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-booster-dlYsusU2e5MlereE.png).

Source comparison: [tactics.tools — Booster Pack](https://tft.tools/info/set-18/tables/booster-pack).

### 10.11 Frontline Foundation and Backline Blueprint

| Augment | Champion | Matching class emblem |
| --- | --- | --- |
| Frontline Foundation | Kobuko / Rek’Sai | Brawler |
| Frontline Foundation | Leona / Ornn | Defender |
| Frontline Foundation | Rakan | Vanguard |
| Backline Blueprint | Azir | Executioner |
| Backline Blueprint | Cassiopeia | Spellweaver |
| Backline Blueprint | Diana | Ravager |
| Backline Blueprint | Mama Beak | Rapidfire |
| Backline Blueprint | Tristana | Hunter |

Frontline delivers a two-star 1-cost; Backline a one-star 3-cost. No pairing probabilities are printed.

Source: [LBB — frontline](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=605,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-frontline-rqILMN9CLnI4pQSr.png).

Source: [LBB — backline](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=605,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-backline-k9XsS4dlP6tXJbcO.png).

### 10.12 Warpath

After 80 player damage, the chest contains three random 5-costs, a two-star 4-cost, and two completed-item anvils. This is the listed cashout, separate from the initial two-star 2-cost. No percentage is printed.

Source: [LBB — warpath](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=239,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-warpath-ASsuUftv0LYshUPS.png).

### 10.13 Slightly Magic Roll

| Die result | Reward |
| --- | --- |
| 1 | 6 free rerolls |
| 2 | 10 gold |
| 3 | 3 gold; two-star 2-cost |
| 4 | Random completed item; Reforger |
| 5 | 160 team Health |
| 6 | Random emblem |

LBB does not print face probabilities. A one-in-six assumption is not substituted.

Source: [LBB — slightly](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=527,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-slightly-JViqTl3OWQozydsl.png).

### 10.14 A Magic Roll

| Dice result | Listed chance | Reward |
| --- | --- | --- |
| Total 4–8, except special triples | 25% | 250 Health for present and future fielded units |
| Total 9–11, except special triples | 36% | Two-star 1-cost; two two-star 2-costs; two-star 3-cost |
| Total 12–15, except special outcomes | 32% | Four copies of one component; Reforger |
| Total 16–17 | 4% | Frying Pan; two random components |
| 111 / 222 / 333 | 1.4% | 4–6 gold; three Lesser Champion Duplicators |
| 444 / 555 / 666 | 1.4% | Tactician’s Cape |
| 626 | 0.5% | Special Golden Egg |

Special outcomes take precedence over ordinary sum bands. The 626 egg hatches after three turns, giving 5 gold, two 5-costs, and Tactician’s Crown. This is distinct from §10.2’s eleven-turn egg.

**Source-value flags:** LBB’s displayed chances total 100.3%. tactics.tools prints 36.1%, 31.5%, and 4.2% for the ordinary middle/high groups and shows only one two-star 2-cost in its champion bundle. Neither source’s presentation is silently substituted for the other. The precise 4/5/6-gold mapping within low triples is not exposed.

Source: [LBB — magicroll](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1145,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-magicroll-jG0e6y3xupbRO0tB.png).

Source comparison: [tactics.tools — A Magic Roll](https://tft.tools/info/set-18/tables/magic-roll).

### 10.15 Expected Unexpectedness

At selection and the start of the next two stages, roll three dice. LBB supplies these stage-specific reward probabilities; it does not map each individual dice result to a row.

| Listed chance | Stage 2 | Stage 3 | Stage 4 |
| --- | --- | --- | --- |
| 36% | Two 4-costs | 5 gold; two Lesser Champion Duplicators | Three 5-costs |
| 32% | Two component anvils; three Reforgers | 3 gold; completed-item anvil | 5 gold; Lucky Item Chest |
| 25% | 9 gold | 18 gold | 20 gold |
| 4% | Artifact anvil | Three components | Random completed item; two components |
| 3% | Tactician’s Crown | Two random emblems | Three 5-costs; Champion Duplicator |

Source: [LBB — expected](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1126,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-expected-xqtp6HzoV9ie6tj5.png).

### 10.16 Missed Connections and Slice of Life

Missed Connections delivers one copy of every 1-cost. In LBB’s circular layout, starting at the top and proceeding clockwise: **Akali, Camille, Varus, Veigar, Ornn, Yorick, Xayah, Karma, Pebbles, Rek’Sai, Rakan, Leona, Kobuko, Cinderling**.

The September 3 layout illustrates overlapping positions: Cinderling/Kobuko/Leona form the upper central stack; Rakan is left; Rek’Sai is lower-left of Karma/Pebbles; the right column runs from the Akali/Camille/Varus cluster through Veigar, Ornn, Yorick, and Xayah. Exact coordinates and the reason the two layouts differ are not stated; this is not a universal coordinate guarantee.

Source: [LBB — missed](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1145,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-missed-aHmKi5ZsgntNoixl.png).

Source: [LBB — missed b](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1145,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-missed-b-bNzAKyp87pTNXMs8.png).

| Slice of Life delivery | Champion |
| --- | --- |
| 2-1 and 2-5 | One random 2-cost each |
| 3-1 and 3-5 | One random 3-cost each |
| 4-1 and 4-5 | One random 4-cost each |
| 5-1 | One random 5-cost; deliveries end |

Source: [LBB — slice](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=597,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-slice-L5z5M6llWeYT8QD0.png).

### 10.17 Hard Commit

Receive an emblem, a matching one-star champion, and 3 gold immediately and at each stage start. Champion cost equals the stage, capped at five.

| Emblem | Stage 2 | Stage 3 | Stage 4 | Stage 5+ |
| --- | --- | --- | --- | --- |
| Blossom | Yunara | Master Yi | Ahri or Sett | Ashe |
| Brawler | Alistar | Krug | Sett | Gnar |
| Elderwood | Alistar or LeBlanc | Hecarim | Ezreal | Gnar |
| Hunter | Caitlyn | Tristana | Sivir | Ashe |
| Juggernaut | Scuttlecrab or Sejuani | Vi | Amumu | Maokai |
| Spellweaver | LeBlanc | Cassiopeia or Fiddlesticks | Ahri | Alune |
| Vanguard | Elise | Diana or Hecarim | Sentinel | Taric |

Selection weights for multiple eligible champions are unspecified. Champion identities and costs were cross-checked against [tactics.tools — units](https://tactics.tools/info/units).

Source: [LBB — commit](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=961,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-commit-T0uUjGvdUbjXdFUt.png).

### 10.18 Solo Leveling

For five combats, team size is one. The fielded champion receives **50% AD, 50% AP, 150% Attack Speed, 10% Critical Strike Chance, 30% Damage Amp, 525 Health, 20% Durability, and 20% Omnivamp**. Each kill gives one XP; afterward receive two components. LBB supplies one fixed bonus row, not star-level scaling.

Source: [LBB — solo leveling](https://www.littlebuddybot.com/tft-augment-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=514,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-solo-leveling-xJ1rjhTwkPe6A1ky.png).

### 10.19 Bonus Gift qualifying sources

Bonus Gift has a 25% chance to create a Gray orb when a qualifying loot orb opens. Whether a reward qualifies depends on how it is delivered, not its gold value. LBB’s embedded table was recovered: **267 records: 138 Orb, 108 Non-Orb, 13 Conditional, 8 Mixed**. The complete factual source-classification ledger appears in Appendix A.1.

Examples: Fae’s Golden Pixies and Loaded Dice/Truce coins are Non-Orb; Teemo mushrooms explicitly carry an ignore flag. Artifactinate and copied units may qualify only when the relevant bench is full. Warpath’s later cashout qualifies, while its initial champion does not. Do not count every item or champion inside a bundled orb as a separate opening.

Source: [LBB — Bonus Gift sources](https://www.littlebuddybot.com/tft-bonus-gift).

## 11. Wisps

### 11.1 General offer and purchase rules

Wisps occupy the rightmost shop slot. Normally, they appear in every other shop and you may buy one per round. After purchasing one, additional Wisps normally stop appearing that round. A Wisp disappears on purchase or when the planning phase ends, revealing the champion behind it.

The set overview says that after Stage 5, every other Wisp comes from the Combat category. Wisps scale as the game progresses, and some have specific eligibility conditions. For example, Hand of Baron requires active Riftbeast.

Categories: Champion, Combat, Gold/XP, Item, Miscellaneous, Risky, and Shop. Blossom can alter the normal appearance and purchase rules.

### 11.2 Selected named effects

| Wisp | Cost | Effect |
| --- | --- | --- |
| Heroic Sacrifice | 5 gold | Empowers the strongest three champions; sacrifices the others. |
| Hand of Baron | 6 gold | Grants the team a Baron buff. |
| Blood Ritual | 6 gold | Lose 10 player Health; gain a Champion Duplicator. |
| Grow Up | 7 gold | Gain 10 XP. |
| Lucky 7 | 7 gold | Gain seven rerolls. |

Source: [tactics.tools — Set 18 overview](https://tactics.tools/info/set-update); [LBB — Wisp database](https://www.littlebuddybot.com/tft-wisps).

### 11.3 Offer windows, variants, eligibility, and cooldowns

The recovered LBB database contains **366 records**. Duplicate names can be separate base, Blossom-upgraded, or Prismatic records. The full factual offer ledger in Appendix A.1 retains those distinctions; it is not an equal-probability selection pool.

| Database band | Rounds |
| --- | --- |
| Early | 2-1–2-7 |
| Early Mid | 3-1–3-4 |
| Mid | 3-5–4-1 |
| Mid Late | 4-2–4-7 |
| Late | 5-1–5-7 |
| Very Late | 6-1–10-1 |

| Wisp | Cost | Offer window | Additional requirement | Re-offer cooldown field |
| --- | --- | --- | --- | --- |
| Heroic Sacrifice | 5 | 4-2–5-7 | Exactly 2 or 3 champions holding 3 items each | 5 |
| Hand of Baron | 6 | 5-1–10-1 | Riftbeast active | 5 |
| Preppers | 2 | 3-1–5-7 | At least two stacking items in the army | 5 |
| Blast / Health / Mana Potion | 1 | 3-1–4-7 | No extra condition listed | 5 |
| Potioncraft | 2 | 5-1–10-1 | No extra condition listed | 5 |
| Blood Ritual | 6 | 4-2–4-7 | Player Health greater than 10; upgraded version greater than 8 | 200 |

**Cooldown rule recovered:** LBB’s header tooltip defines the number as **Wisp shops after this Wisp is offered during which it cannot appear again**. The page groups cooldowns across Blossom variants. Thus 5/10/20/200 are shop counts, not round counts or selection weights; 200 is not relabeled “once per game.” Additional reset exceptions are not specified. Blank conditions mean no extra condition is listed, not proof of unrestricted eligibility.

Source: [LBB — Wisp database](https://www.littlebuddybot.com/tft-wisps).

### 11.4 Heroic Sacrifice and Hand of Baron

Heroic Sacrifice sacrifices other allies and empowers the strongest three champions:

| Variant | AD/AP | Attack Speed | Health | Armor / MR | Omnivamp |
| --- | --- | --- | --- | --- | --- |
| Base | 30% | 30% | 1200 | 30 / 30 | 10% |
| Blossom upgrade | 40% | 40% | 1500 | 40 / 40 | 12% |

Source: [LBB — heroic](https://www.littlebuddybot.com/tft-wisp-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=689,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-heroic-CuTPwuWhvrDKTplg.png).

Hand of Baron applies these team bonuses:

| Variant | AD/AP | AS | Crit chance | Damage Amp | Health | Armor / MR | Durability | Omnivamp |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Base | 3% | 3% | 10% | 3% | 33 | 3 / 3 | 3% | 3% |
| Blossom upgrade | 5% | 5% | 15% | 5% | 55 | 5 / 5 | 5% | 5% |

Source: [LBB — baron](https://www.littlebuddybot.com/tft-wisp-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=652,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-baron-2czwyKRXSKn3s2sN.png).

### 11.5 Preppers

These are starting values for the next combat, as listed by LBB. “Stacks” is retained as the source unit; no extra per-stack stat conversion is inferred.

| Item | Base Wisp | Blossom upgrade |
| --- | --- | --- |
| Archangel’s Staff | 20 AP | 30 AP |
| Radiant Archangel’s Staff | 30 AP | 45 AP |
| Guinsoo’s Rageblade | 20 stacks | 30 stacks |
| Radiant Guinsoo’s Rageblade | 30 stacks | 45 stacks |
| Titan’s Resolve | 7 stacks | 14 stacks |
| Radiant Titan’s Resolve | 7 stacks | 14 stacks |
| Kraken’s Fury | 4 stacks | 8 stacks |
| Radiant Kraken’s Fury | 4 stacks | 8 stacks |
| Rapid Firecannon | 3 stacks | 5 stacks |
| Mogul’s Mail | 10 stacks | 20 stacks |
| Flickerblades | 4 stacks | 6 stacks |
| Seeker’s Armguard | 10 stacks | 15 stacks |

Source: [LBB — preppers](https://www.littlebuddybot.com/tft-wisp-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1058,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-preppers-8JpI5k5nuExKniOR.png).

Item-icon identities checked against the [tactics.tools item catalog](https://tactics.tools/info/items).

### 11.6 Potions and Potioncraft

| Potion | Normal effect | Radiant effect |
| --- | --- | --- |
| Blast | At 8 seconds: knock up enemies within 3 hexes for 1.75 seconds | At 8 seconds: 4-hex radius, 2-second knockup |
| Health | Below 50% holder Health: restore 750 Health over 3 seconds | Restore 850 holder Health and 150 allied Health over 3 seconds |
| Mana | 20 starting Mana; on cast, restore 80 Mana over 5 seconds | 20 starting Mana; on cast, restore 90 holder Mana and 10 allied Mana over 5 seconds |

The individual Potion Wisps give one temporary equippable potion. Potioncraft gives three; Blossom upgrades replace them with Radiant potions. The sources call them temporary but do not expose an exact expiration round or whether every possible repeat trigger is allowed. Those duration/retrigger details remain unresolved.

Source: [LBB — potions](https://www.littlebuddybot.com/tft-wisp-tables); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1338,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-potions-d1O7337HxGLUpWYc.png).

### 11.7 Prismatic Blossom Wisp effects

LBB exposes 19 Prismatic entries. Costs are 0 except Ultra Ascension at 1. The ledger preserves their separate offer records.

| Wisp | Published Prismatic effect |
| --- | --- |
| Barrier | 7,500 team Shield, decaying over 30 seconds |
| Blaze | Board-wide spreading fire; numerical damage/timing unresolved |
| Combust | On ally death: explosion for 100% maximum Health magic damage |
| Counterspell | Enemy maximum Mana +150 until next cast |
| Downpour | 15 team Mana Regen |
| Giant’s Aura | Highest-Health ally empowered; numerical bonuses unresolved |
| Hireling | Three temporary two-star 5-costs, each with two recommended items |
| Hugify | 2,500 Health for the ten highest-Health units |
| Hummingbird | 100% Attack Speed for the ten highest-AS units |
| Late Bloomer | Five temporary four-star 1-costs |
| Lightning Storm | Every 0.15 seconds: 5% maximum-Health true damage to an enemy |
| Lucky 7 | 777 shop rerolls |
| Phantom Armor | Six temporary Radiant Warmog’s Armors; five Removers |
| Stand Alone | Units alone in a row: 100% Health and 150% Damage Amp |
| Tattered Armor | 90% Shred and Sunder for 45 seconds |
| Treetop Archers | Many archers attack; exact count/damage/frequency unresolved |
| Tremors | Every 3 seconds: 1.5-second enemy Stun |
| Truce | 100 gold to player; 1 gold to opponent |
| Ultra Ascension | At 12 seconds: 300% team Damage Amp |

These are the effects actually exposed in the embedded data, not extrapolations from ordinary Wisps. A qualitative Prismatic entry is retained as a gap rather than assigned a multiplier.

Source: [LBB — Wisp database](https://www.littlebuddybot.com/tft-wisps).

## 12. Selected item and effect references

| Item | Relevant effect |
| --- | --- |
| Evenshroud | 30% Sunder within two hexes; 15 Armor and Magic Resist for the first fifteen seconds. |
| Last Whisper | Attacks and ability damage apply 30% Sunder for three seconds; does not stack. |
| Morellonomicon | Attacks and abilities apply 1% Burn and 33% Wound for ten seconds. |
| Gargoyle Stoneplate | 10 Armor and Magic Resist per enemy targeting the holder. |
| Giant Slayer | 15% additional Damage Amp against Tanks. |
| Radiant Evenshroud | 30% Sunder within three hexes; 50 Armor and Magic Resist for twenty seconds. |
| Radiant Last Whisper | 30% Sunder for the rest of combat; does not stack. |
| Radiant Lucky Item Chest | Used on a champion to choose from an item armory suited to that champion. |

This is a selected lookup, not an exhaustive catalog of every source of these effects.

Source: [tactics.tools — items](https://tactics.tools/info/items).

### 12.1 Emblem recipes and bonuses

Each crafted emblem combines the named catalyst and component; it grants its named trait. Bonuses below are those shown in LBB’s current Set 18 graphic.

| Emblem | Catalyst + component | Listed bonus |
| --- | --- | --- |
| Blossom | Spatula + Needlessly Large Rod | 250 Health; 10% AD/AP |
| Inferno | Spatula + Recurve Bow | 40% AS |
| Fae | Spatula + B.F. Sword | 250 Health; 15% AD/AP |
| Primal | Spatula + Sparring Gloves | 250 Health; 25% AS; 20% Crit chance |
| Lunar | Spatula + Tear | 20% AS; 3 Mana Regen |
| Blackthorn | Spatula + Giant’s Belt | 250 Health; 15% AD/AP |
| Elderwood | Spatula + Chain Vest | 25% AS; 35 Armor and MR |
| Sprykin | Spatula + Negatron Cloak | 10% AS; 20 Armor and MR; riding BFF adds 30% AS and 20 MR |
| Coven | Uncraftable in this graphic | 150 Health |
| Flora Fatalis | Uncraftable in this graphic | 250 Health; 2 Mana Regen |
| Spellweaver | Frying Pan + Needlessly Large Rod | 25% AP; 2 Mana whenever an ally casts |
| Rapidfire | Frying Pan + Recurve Bow | 20% AS; attacks add 1% target maximum Health true damage |
| Hunter | Frying Pan + B.F. Sword | 30% AD; takedowns grant 18% AD |
| Executioner | Frying Pan + Sparring Gloves | 20% Crit chance; 8% Crit damage; execute below 8% target maximum Health |
| Invoker | Frying Pan + Tear | 3 Mana Regen; on cast gain AP equal to 10% Mana spent |
| Brawler | Frying Pan + Giant’s Belt | 250 Health; attacks add 2% holder maximum Health magic damage |
| Vanguard | Frying Pan + Chain Vest | 30 Armor and MR; survive 22 seconds in player combat for 1 player Health |
| Ravager | Frying Pan + Negatron Cloak | 20% AD/AP; 20 Armor and MR; 3% Damage Amp per 300 Health restored |
| Defender | Uncraftable in this graphic | 30 Armor and MR; combat start: 6% AS per ally starting in front row |
| Juggernaut | Uncraftable in this graphic | 350 Health; 15 Mana whenever a Juggernaut dies |

This is the graphic’s 20-emblem list. It does not imply recipes for unlisted traits or guarantee all emblems are offered by every emblem source.

Source: [LBB — emblems](https://www.littlebuddybot.com/tft-other-info); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=1553,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.1-emblems-tFlTL8EY4n6OROLo.png).

### 12.2 Solo Stage 1 reference

LBB’s September 16 chart lists **Akali, Camille, Rek’Sai, and Yorick** as solo 1-cost options at **1-3**, and **Camille** at **1-4**, each with placement marked “anywhere.” The graphic does not state additional item/star assumptions or outcomes for every other champion; those are not inferred. This is separate from the Solo Leveling augment.

Source: [LBB — solo](https://www.littlebuddybot.com/tft-other-info); [reviewed graphic](https://assets.zyrosite.com/cdn-cgi/image/format=auto,w=1440,h=715,fit=crop/A85M9B5RkKFMqVXr/set-18-tables-patch-18.2-solo-9Qie2fmemkp6YZYx.png).

## 13. Published differences and incomplete fields

### 13.1 XP disagreement

LBB’s September 16 graphic gives 68 XP for 8→9 and 9→10. tactics.tools’ 18.2 patch notes give 64 for both. Both are retained in §1.3. No accepted later note recovered here establishes which text supersedes the other.

Sources: [LBB — shop odds](https://www.littlebuddybot.com/tft-shop-odds), [tactics.tools — 18.2 notes](https://tactics.tools/info/patch-notes/18.2).

### 13.2 Source differences requiring care

| Topic | Difference retained | Reference |
| --- | --- | --- |
| Encounters | LBB’s 20 rows total 103%; tactics.tools’ same rows total 88% | §2.1 |
| Coven generation | Four Coven: LBB 25 Essence per loss; tactics.tools 32 | §4.1 |
| Coven rewards | LBB’s expanded September 11 table differs from the general tactics.tools table; 250-Essence Morgana bundle has 5 gold in LBB versus 3 in 18.2 notes | §4.2–4.3 |
| Blackthorn | LBB’s separate 4/6-trait matrix differs from tactics.tools’ repeated “60% stronger” wording; one LBB AD cell is also unusual | §5.1–5.3 |
| Lux | Inferno mana, Lunar Vulnerable, and Primal AS differ between accepted sources | §8.3 |
| Sprykin | Five-Sprykin ability sharing: LBB 50%, tactics.tools 100%; extra heal recipient scope also needs clarification | §9.1 |
| Golden Egg | One 10% bundle has Artifact + Radiant in LBB versus two Artifacts in tactics.tools | §10.2 |
| Trait Ladder | Rungs 7, 10, and 11 differ between LBB and the general tactics.tools table | §10.7 |
| Booster Pack | Some star levels/package contents differ, and the + final row is 4% versus 3% | §10.10 |
| A Magic Roll | Rounded chances and the number of two-star 2-costs differ | §10.14 |

The sources for each difference appear beside the affected table. A newer date is evidence about a document revision, not proof that every value in it is synchronized. No conflict was settled by importing another TFT site’s values.

### 13.3 Missing data is not conflicting data

Retrieval succeeded for the current LBB graphics and the three embedded data tables. Remaining gaps concern source content or interpretation, not a blanket inability to read LBB:

- Exact encounter probabilities; underlying augment-sequence probabilities and encounter-conditioned distributions.
- Player-damage exceptions; Gold Subscription draw cadence; subscription behavior beyond the published stages.
- Riftbeast’s complete lineup weights by gameplay state and three-star ownership.
- Fae counter reset/carryover/deactivation behavior.
- Independent BFF base stats; the Sprykin recipient-scope conflict.
- Ornn’s Forge Power reward thresholds.
- Primal’s explicit two/four-breakpoint mapping and Tiger stacking interpretation.
- Loaded Dice’s exact modified dice distribution; Blossom’s Call Stage-7+ behavior/selection weights; Hard Commit champion selection weights.
- Exact low-triple Magic Roll gold mapping; some encounter/augment selection probabilities.
- Wisp selection weights, cooldown reset exceptions, temporary-item expiry/retrigger details, and numerical Prismatic Blaze / Giant’s Aura / Treetop Archers effects.
- A definitive, separately labeled disabled-augment inventory; unmarked modes or missing records are not proof of disablement.

Older-set tables and assumed uniform probabilities were not used to fill these gaps. The complete reviewed field ledgers below preserve the data that was available.

## Appendix A. Coverage checklist and recovered database fields

Every item in the original incomplete-section checklist was revisited. “Recovered” means the accepted source was directly read; “partial” identifies an explicit remaining content or interpretation gap. It does not mean that a source was proved wrong.

### A.1 Embedded databases

| LBB page | Retrieval result | Coverage |
| --- | --- | --- |
| Wisp database | 366 source records recovered | Variant identity, tier, cost, offer bands, mode flags, cooldowns, requirements, and exclusions in A.1.1; selected mechanics in §11 |
| Augment database | 252 records: 249 augments and 3 encounter records | Stage/mode flags, single-player flags, prerequisites, and mutual exclusions in A.1.2 |
| Bonus Gift | 267 source records recovered | All published classifications, orb counts, and delivery notes in A.1.3 |

The ledgers are factual field transcriptions, not copied tooltip collections. They cover all records returned by those embedded LBB tables on the check date, not a guarantee of every in-game entry. Empty fields are represented as “—”; they are never filled by inference. The external storage belongs to the data embedded by LBB, so the source authority remains LBB.

#### A.1.1 Wisp offer ledger

Bands: E = 2-1–2-7; EM = 3-1–3-4; M = 3-5–4-1; ML = 4-2–4-7; L = 5-1–5-7; VL = 6-1–10-1. Modes are Standard / Doubles / Tocker’s, in that order: Y means the source marks available; — means not marked. Tier values such as “2.Rabbit” are preserved literally because their extra subtype is not explained. “CD” counts Wisp shops after an offer during which that Wisp cannot reappear; LBB groups cooldowns across Blossom variants. Blossom and Prismatic variants remain separate records.

Source: [LBB — Wisp database](https://www.littlebuddybot.com/tft-wisps).

<details>
<summary>All 366 recovered Wisp offer records</summary>

| Wisp / variant | Tier | Gold | Bands | CD | Modes | Condition | Incompatible entries |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Abandon Ship [Base] | 3 | 0 | EM | 5 | Y/Y/Y | C61 | NO SCOUT NO PIVOT; Worth the Wait; Worth the Wait II; Weight The Worth; Hard Commit; Luxury Subscription; Frontline Foundation; Backline Blueprint; Unrivaled; The Trait Tree; Trait Ladder |
| Abandon Ship [Blossom] | 3 | 0 | EM | 5 | Y/Y/Y | C61 | NO SCOUT NO PIVOT; Worth the Wait; Worth the Wait II; Weight The Worth; Hard Commit; Luxury Subscription; Frontline Foundation; Backline Blueprint; Unrivaled; The Trait Tree; Trait Ladder |
| Aftershock [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | — | Arcane Viktor-y |
| Aftershock [Blossom] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | — | Arcane Viktor-y |
| All Fives [Base] | 3 | 8 | VL | 5 | Y/Y/Y | C14 | — |
| All Fives [Blossom] | 3 | 8 | VL | 5 | Y/Y/Y | C14 | — |
| All Fours [Base] | 1 | 3 | L | 5 | Y/Y/Y | C36 | — |
| All Fours [Blossom] | 1 | 3 | L | 5 | Y/Y/Y | C36 | — |
| All Ones [Base] | 1 | 0 | E | 5 | Y/Y/Y | C34 | — |
| All Ones [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | C34 | — |
| All Threes [Base] | 1 | 2 | M,ML | 5 | Y/Y/Y | C34 | — |
| All Threes [Blossom] | 1 | 2 | M,ML | 5 | Y/Y/Y | C34 | — |
| All Twos [Base] | 1 | 1 | E,EM | 5 | Y/Y/Y | C34 | — |
| All Twos [Blossom] | 1 | 1 | E,EM | 5 | Y/Y/Y | C34 | — |
| Animate Shop [Base] | 2 | 8 | ML,L | 5 | Y/Y/Y | C13 | — |
| Animate Shop [Blossom] | 2 | 8 | ML,L | 5 | Y/Y/Y | C13 | — |
| Apprentice [Base] | 2 | 3 | E | 5 | Y/Y/Y | — | — |
| Apprentice [Blossom] | 2 | 2 | E | 5 | Y/Y/Y | — | — |
| Artifactinate [Base] | 2 | 2 | E,EM | 20 | Y/Y/Y | C28 | Spirit Of Redemption; Promised Protection; Lucky Gloves; Lucky Gloves+; Solo Plate; Seraphim's Staff; Heart of Steel; Deadlier Blades; Deadlier Caps; Living Forge; Forged In Strength; Portable Forge |
| Artifactinate [Blossom] | 2 | 2 | E,EM | 20 | Y/Y/Y | C28 | Spirit Of Redemption; Promised Protection; Lucky Gloves; Lucky Gloves+; Solo Plate; Seraphim's Staff; Heart of Steel; Deadlier Blades; Deadlier Caps; Living Forge; Forged In Strength; Portable Forge |
| Backrow Star [Base] | 2 | 1 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Backrow Star [Blossom] | 2 | 1 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Bark Armor [Base] | 1 | 0 | E | 5 | Y/Y/Y | C69 | — |
| Bark Armor [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | C69 | — |
| Barrier [Base] | 2 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Barrier [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Barrier [Blossom] | 2 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Barter [Base] | 1 | 2 | M,ML,L | 5 | Y/Y/Y | — | — |
| Barter [Blossom] | 1 | 2 | M,ML,L | 5 | Y/Y/Y | — | — |
| Bear's Visit [Base] | 2 | 3 | M,ML,L | 5 | Y/Y/Y | C80 | — |
| Beggar's Wisp [Base] | 1 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Beggar's Wisp [Blossom] | 1 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Big Boom [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Big Boom [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Big Guns [Base] | 2 | 8 | ML | 5 | Y/Y/Y | — | — |
| Big Guns [Blossom] | 2 | 7 | ML | 5 | Y/Y/Y | — | — |
| Blast Potion [Base] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Blast Potion [Blossom] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Blaze [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Blaze [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Blaze [Blossom] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Blood and Iron [Base] | 2.Rabbit | 3 | EM,M | 20 | Y/Y/Y | — | Solo Leveling |
| Blood and Iron [Blossom] | 2.Rabbit | 3 | E | 20 | Y/Y/Y | — | Solo Leveling |
| Blood Money [Base] | 1 | 2 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Blood Money [Blossom] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Blood Ritual [Base] | 3 | 6 | ML | 200 | Y/—/— | C57 | — |
| Blood Ritual [Blossom] | 3 | 6 | ML | 200 | Y/—/— | C60 | — |
| Booster Shot [Base] | 2 | 6 | L,VL | 5 | Y/Y/Y | C15 | — |
| Booster Shot [Blossom] | 2 | 6 | L,VL | 5 | Y/Y/Y | C15 | — |
| Border Village [Base] | 3 | 3 | EM,M | 5 | Y/Y/Y | — | — |
| Border Village [Blossom] | 3 | 2 | EM,M | 5 | Y/Y/Y | — | — |
| Borrowed Gear [Base] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Borrowed Gear [Blossom] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Bronze Spoon [Base] | 2 | 3 | E,EM,M | 5 | Y/Y/Y | — | — |
| Bronze Spoon [Blossom] | 2 | 2 | E,EM,M | 5 | Y/Y/Y | — | — |
| Bulwark [Base] | 2 | 3 | ML,L,VL | 5 | Y/Y/Y | C22 | — |
| Bulwark [Blossom] | 2 | 3 | ML,L,VL | 5 | Y/Y/Y | C22 | — |
| Bunch-o'-Belts [Base] | 1 | 1 | M,ML | 5 | Y/Y/Y | — | — |
| Bunch-o'-Belts [Blossom] | 1 | 1 | M,ML | 5 | Y/Y/Y | — | — |
| Circle of Elders [Base] | 3 | 45 | VL | 5 | Y/Y/Y | — | — |
| Circle of Elders [Blossom] | 3 | 40 | VL | 5 | Y/Y/Y | — | — |
| Coin Flip [Base] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Coin Flip [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Combust [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Combust [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Combust [Blossom] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Component Bounty [Base] | 1.Rabbit | 4 | EM,M,ML | 5 | Y/Y/— | C65 | — |
| Component Bounty [Blossom] | 1.Rabbit | 2 | EM,M,ML | 5 | Y/Y/— | C65 | — |
| Counterspell [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Counterspell [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Counterspell [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Crystal Ball [Base] | 1 | 1 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Crystal Ball [Blossom] | 1 | 1 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Curio Cart [Base] | 2 | 0 | EM,M,ML | 20 | Y/Y/Y | C11 | — |
| Curio Cart [Blossom] | 2 | 0 | M,ML,L | 20 | Y/Y/Y | C11 | — |
| Cutpurse [Base] | 2 | 2 | M,ML | 5 | Y/Y/Y | — | — |
| Cutpurse [Blossom] | 2 | 2 | M,ML | 5 | Y/Y/Y | — | — |
| Die Roll [Base] | 1 | 2 | EM,M | 5 | Y/Y/Y | — | — |
| Die Roll [Blossom] | 1 | 3 | EM,M | 5 | Y/Y/Y | — | — |
| Diversified [Base] | 2 | 3 | ML,L | 5 | Y/Y/Y | C32 | — |
| Diversified [Blossom] | 2 | 3 | ML,L | 5 | Y/Y/Y | C32 | — |
| Doodad Bag [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Doodad Bag [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Doodad Jar [Base] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Doodad Jar [Blossom] | 1 | 1 | E | 5 | Y/Y/Y | — | — |
| Doodad Sack [Base] | 2 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Doodad Sack [Blossom] | 2 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Downpour [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Downpour [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Downpour [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Drought [Base] | 1 | 1 | E | 5 | Y/Y/— | C70 | — |
| Drought [Blossom] | 1 | 1 | E | 5 | Y/Y/— | C70 | — |
| Early Fix [Base] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Early Fix [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Essence Theft [Base] | 1 | 1 | E,EM,M | 5 | Y/Y/Y | C39 | — |
| Essence Theft [Blossom] | 1 | 1 | E,EM,M | 5 | Y/Y/Y | C39 | — |
| Experienced [Base] | 1 | 1 | E | 5 | Y/Y/Y | — | — |
| Experienced [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Fellowship [Base] | 2 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Fellowship [Blossom] | 2 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Fertilize [Base] | 1 | 1 | E,EM | 5 | Y/Y/Y | — | — |
| Fertilize [Blossom] | 1 | 1 | E,EM | 5 | Y/Y/Y | — | — |
| Flash Fire [Base] | 1 | 1 | M,ML,L | 5 | Y/Y/Y | C52 | — |
| Flash Fire [Blossom] | 1 | 1 | M,ML,L | 5 | Y/Y/Y | C52 | — |
| Flip Frenzy [Base] | 2 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Flip Frenzy [Blossom] | 2 | 0 | EM,M | 5 | Y/Y/Y | — | — |
| Flood [Base] | 1 | 1 | E | 5 | Y/Y/— | C67 | — |
| Flood [Blossom] | 1 | 1 | E | 5 | Y/Y/— | C67 | — |
| Flow [Base] | 1 | 3 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Flow [Blossom] | 1 | 3 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Forest Guide [Base] | 3 | 5 | E | 5 | Y/Y/Y | — | — |
| Forest Guide [Blossom] | 3 | 4 | E | 5 | Y/Y/Y | — | — |
| Forest Mage [Base] | 1 | 1 | M,ML,L,VL | 5 | Y/Y/Y | C42 | — |
| Forest Mage [Blossom] | 1 | 1 | M,ML,L,VL | 5 | Y/Y/Y | C42 | — |
| Forest Twins [Base] | 2 | 4 | E | 5 | Y/Y/Y | — | — |
| Forest Twins [Blossom] | 2 | 5 | E | 5 | Y/Y/Y | — | — |
| Found Friend [Base] | 1 | 0 | E | 5 | Y/Y/Y | C69 | — |
| Found Friend [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | C69 | — |
| Freeroller [Base] | 1 | 2 | E,EM,M | 5 | Y/Y/Y | — | — |
| Freeroller [Blossom] | 1 | 2 | E,EM,M | 5 | Y/Y/Y | — | — |
| Giant Growth [Base] | 3 | 4 | L,VL | 5 | Y/Y/Y | — | — |
| Giant Growth [Blossom] | 3 | 4 | L,VL | 5 | Y/Y/Y | — | — |
| Giant's Aura [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | C08 | — |
| Giant's Aura [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Giant's Aura [Blossom] | 3 | 3 | L,VL | 5 | Y/Y/Y | C08 | — |
| Golden Goose [Base] | 2 | 1 | ML,L | 5 | Y/Y/Y | — | — |
| Golden Goose [Blossom] | 2 | 1 | ML,L | 5 | Y/Y/Y | — | — |
| Golden Road [Base] | 2.Rabbit | 2 | E,EM | 5 | Y/Y/— | C65 | — |
| Golden Road [Blossom] | 2.Rabbit | 2 | E,EM | 5 | Y/Y/— | C65 | — |
| Good Loss [Base] | 2.Rabbit | 4 | EM,M | 5 | Y/Y/— | C68 | — |
| Good Loss [Blossom] | 2.Rabbit | 4 | EM,M | 5 | Y/Y/— | C68 | — |
| Grandmaster [Base] | 3 | 18 | VL | 5 | Y/Y/Y | — | — |
| Grandmaster [Blossom] | 3 | 14 | VL | 5 | Y/Y/Y | — | — |
| Greater Chaos [Base] | 3 | 4 | L,VL | 5 | Y/Y/Y | — | — |
| Greater Chaos [Blossom] | 3 | 4 | L,VL | 5 | Y/Y/Y | — | — |
| Grow Up [Base] | 2 | 7 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Grow Up [Blossom] | 2 | 7 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Hand Of Baron [Base] | 3 | 6 | L,VL | 5 | Y/Y/Y | C73 | — |
| Hand Of Baron [Blossom] | 3 | 6 | L,VL | 5 | Y/Y/Y | C73 | — |
| Healing Pool [Base] | 2 | 2 | E,EM | 10 | Y/—/— | C12 | — |
| Healing Pool [Blossom] | 2 | 2 | M,ML,L | 10 | Y/—/— | C12 | — |
| Health Potion [Base] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Health Potion [Blossom] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Heated Rivalry [Base] | 1 | 3 | E | 5 | Y/Y/Y | — | — |
| Heated Rivalry [Blossom] | 1 | 3 | E | 5 | Y/Y/Y | — | — |
| Hero Of Prophecy [Base] | 3 | 35 | VL | 200 | Y/Y/Y | C30 | — |
| Hero Of Prophecy [Blossom] | 3 | 33 | VL | 200 | Y/Y/Y | C30 | — |
| Hero's Entrance [Base] | 3 | 2 | VL | 5 | Y/—/Y | C09 | — |
| Hero's Entrance [Blossom] | 3 | 2 | VL | 5 | Y/—/Y | C09 | — |
| Heroic Sacrifice [Base] | 3 | 5 | ML,L | 5 | Y/Y/Y | C48 | Makeshift Armor I; Makeshift Armor II |
| Heroic Sacrifice [Blossom] | 3 | 5 | ML,L | 5 | Y/Y/Y | C48 | Makeshift Armor I; Makeshift Armor II |
| Hireling [Base] | 3 | 2 | VL | 5 | Y/Y/Y | — | — |
| Hireling [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Hireling [Blossom] | 3 | 5 | VL | 5 | Y/Y/Y | — | — |
| Homing Fireflies [Base] | 2 | 2 | M,ML,L,VL | 5 | Y/Y/Y | C17 | — |
| Homing Fireflies [Blossom] | 2 | 2 | M,ML,L,VL | 5 | Y/Y/Y | C17 | — |
| Hugify [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Hugify [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Hugify [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Hummingbird [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Hummingbird [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Hummingbird [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Idle Craftsman [Base] | 2 | 4 | EM,M | 20 | Y/Y/Y | C10 | — |
| Idle Craftsman [Blossom] | 2 | 2 | EM,M | 20 | Y/Y/Y | C10 | — |
| Improved Reach [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | C19 | — |
| Improved Reach [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | C19 | — |
| Infliction [Base] | 3 | 4 | L,VL | 5 | Y/Y/Y | C64 | — |
| Infliction [Blossom] | 3 | 4 | L,VL | 5 | Y/Y/Y | C64 | — |
| Iron Core [Base] | 2 | 1 | ML,L | 5 | Y/Y/Y | — | Solo Plate |
| Iron Core [Blossom] | 2 | 1 | ML,L | 5 | Y/Y/Y | — | Solo Plate |
| Ironwood [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Ironwood [Blossom] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Journeyman [Base] | 2 | 6 | E,EM | 5 | Y/Y/Y | — | — |
| Journeyman [Blossom] | 2 | 5 | E,EM | 5 | Y/Y/Y | — | — |
| Jungling [Base] | 2 | 4 | EM,M,ML | 5 | Y/Y/Y | C73 | — |
| Jungling [Blossom] | 2 | 3 | EM,M,ML | 5 | Y/Y/Y | C73 | — |
| Killer's Regret [Base] | 3 | 1 | L,VL | 5 | Y/Y/Y | — | — |
| Killer's Regret [Blossom] | 3 | 1 | L,VL | 5 | Y/Y/Y | — | — |
| Killing Frenzy [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | C06 | — |
| Killing Frenzy [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | C06 | — |
| Knick-Knack Bag [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | C05 | — |
| Knick-Knack Bag [Blossom] | 1 | 2 | EM,M | 5 | Y/Y/Y | C05 | — |
| Knick-Knack Jar [Base] | 1 | 0 | E | 5 | Y/Y/Y | C05 | — |
| Knick-Knack Jar [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | C05 | — |
| Knick-Knack Sack [Base] | 2 | 3 | L,VL | 5 | Y/Y/Y | C05 | — |
| Knick-Knack Sack [Blossom] | 2 | 3 | L,VL | 5 | Y/Y/Y | C05 | — |
| Late Bloomer [Base] | 3 | 4 | ML,L | 5 | Y/Y/Y | — | — |
| Late Bloomer [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Late Bloomer [Blossom] | 3 | 4 | ML,L | 5 | Y/Y/Y | — | — |
| Lesser Chaos [Base] | 1 | 1 | E,EM | 5 | Y/Y/Y | — | — |
| Lesser Chaos [Blossom] | 1 | 1 | E,EM | 5 | Y/Y/Y | — | — |
| Life Debt [Base] | 2 | 0 | L,VL | 5 | Y/Y/Y | C35 | — |
| Life Debt [Blossom] | 2 | 0 | L,VL | 5 | Y/Y/Y | C35 | — |
| Lightning Storm [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Lightning Storm [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Lightning Storm [Blossom] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Lightning Strike [Base] | 1 | 1 | ML,L | 5 | Y/Y/Y | — | — |
| Lightning Strike [Blossom] | 1 | 1 | ML,L | 5 | Y/Y/Y | — | — |
| Living Soil [Base] | 2 | 2 | ML,L | 5 | Y/Y/Y | — | — |
| Living Soil [Blossom] | 2 | 2 | ML,L | 5 | Y/Y/Y | — | — |
| Lost Travelers [Base] | 1 | 3 | E | 5 | Y/Y/Y | — | — |
| Lost Travelers [Blossom] | 1 | 4 | E | 5 | Y/Y/Y | — | — |
| Lucky 7 [Base] | 2 | 7 | VL | 5 | Y/Y/Y | — | — |
| Lucky 7 [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Lucky 7 [Blossom] | 2 | 7 | VL | 5 | Y/Y/Y | — | — |
| Major Gambit [Base] | 2.Rabbit | 3 | ML,L | 5 | Y/Y/— | C65 | — |
| Major Gambit [Blossom] | 2.Rabbit | 3 | ML,L | 5 | Y/Y/— | C65 | — |
| Major Polymorph [Base] | 2 | 0 | ML,L | 5 | Y/Y/Y | C04 | NO SCOUT NO PIVOT |
| Major Polymorph [Blossom] | 2 | 0 | ML,L | 5 | Y/Y/Y | C04 | NO SCOUT NO PIVOT |
| Mana Potion [Base] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Mana Potion [Blossom] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Mana-Rich Soil [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | C18 | — |
| Mana-Rich Soil [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | C18 | — |
| Marksmen's Gale [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C21 | — |
| Marksmen's Gale [Blossom] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C21 | — |
| Marksmen's Marks [Base] | 2 | 3 | L,VL | 5 | Y/Y/Y | C21 | — |
| Marksmen's Marks [Blossom] | 2 | 3 | L,VL | 5 | Y/Y/Y | C21 | — |
| Mercenary Force [Base] | 2 | 3 | ML,L | 5 | Y/Y/Y | C29 | — |
| Mercenary Force [Blossom] | 2 | 3 | ML,L | 5 | Y/Y/Y | C29 | — |
| Middle Path [Base] | 2 | 4 | M,ML | 5 | Y/Y/Y | — | — |
| Middle Path [Blossom] | 2 | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Minor Blood Ritual [Base] | 2 | 3 | E,EM | 5 | Y/—/— | C58 | — |
| Minor Blood Ritual [Blossom] | 2 | 3 | E,EM | 5 | Y/—/— | C56 | — |
| Minor Gambit [Base] | 1.Rabbit | 1 | E | 5 | Y/Y/— | C66 | — |
| Minor Gambit [Blossom] | 1.Rabbit | 1 | E | 5 | Y/Y/— | C66 | — |
| Minor Polymorph [Base] | 1 | 0 | E,EM | 5 | Y/Y/Y | C01 | NO SCOUT NO PIVOT |
| Minor Polymorph [Blossom] | 1 | 0 | E,EM | 5 | Y/Y/Y | C01 | NO SCOUT NO PIVOT |
| Mitosis [Base] | 1 | 1 | E | 5 | Y/Y/Y | — | — |
| Mitosis [Blossom] | 1 | 0 | E | 5 | Y/Y/Y | — | — |
| Moonlight Ritual [Base] | 2 | 2 | EM,M,ML | 5 | Y/Y/Y | C02 | — |
| Moonlight Ritual [Blossom] | 2 | 2 | EM,M,ML | 5 | Y/Y/Y | C02 | — |
| Moonrise [Base] | 1 | 2 | ML,L | 5 | Y/Y/Y | C55 | — |
| Moonrise [Blossom] | 1 | 2 | ML,L | 5 | Y/Y/Y | C55 | — |
| Nature's Ally [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Nature's Ally [Blossom] | 2 | 2 | EM,ML | 5 | Y/Y/Y | — | — |
| Nature's Wrath [Base] | 3 | 1 | VL | 5 | Y/Y/Y | C33 | — |
| Nature's Wrath [Blossom] | 3 | 1 | VL | 5 | Y/Y/Y | C33 | — |
| Payday [Base] | 2.Rabbit | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Payday [Blossom] | 2.Rabbit | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Peddler [Base] | 2 | 0 | ML,L | 20 | Y/Y/Y | C11 | — |
| Peddler [Blossom] | 2 | 0 | ML,L | 20 | Y/Y/Y | C11 | — |
| Petrified Dummy [Base] | 1 | 2 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Petrified Dummy [Blossom] | 1 | 2 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Petrify Shields [Base] | 1 | 1 | ML,VL | 5 | Y/Y/Y | — | — |
| Petrify Shields [Blossom] | 1 | 1 | ML,VL | 5 | Y/Y/Y | — | — |
| Phantom Armor [Base] | 2 | 2 | EM,M,ML,L | 5 | Y/Y/Y | — | — |
| Phantom Armor [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Phantom Armor [Blossom] | 2 | 2 | EM,M,ML,L | 5 | Y/Y/Y | — | — |
| Phantom Emblem [Base] | 3 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Phantom Emblem [Blossom] | 3 | 1 | L,VL | 5 | Y/Y/Y | — | — |
| Phantom Gloves [Base] | 2 | 3 | EM,M,ML,L | 5 | Y/Y/Y | — | — |
| Phantom Gloves [Blossom] | 2 | 3 | EM,M,ML,L | 5 | Y/Y/Y | — | — |
| Phantom Splash [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C25 | Trait Ladder |
| Phantom Splash [Blossom] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C31 | Trait Ladder |
| Phantom Vest [Base] | 2 | 2 | EM,M,ML,L | 5 | Y/Y/Y | — | — |
| Phantom Vest [Blossom] | 2 | 2 | EM,M,ML,L | 5 | Y/Y/Y | — | — |
| Plated Shields [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Plated Shields [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Pocket Change [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | C16 | — |
| Pocket Change [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | C16 | — |
| Polymorph [Base] | 1 | 0 | E,EM,M | 5 | Y/Y/Y | C03 | NO SCOUT NO PIVOT |
| Polymorph [Blossom] | 1 | 0 | E,EM,M | 5 | Y/Y/Y | C03 | NO SCOUT NO PIVOT |
| Potioncraft [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Potioncraft [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Potted Lifebloom [Base] | 2 | 1 | EM,M,ML | 5 | Y/Y/Y | C44 | — |
| Potted Lifebloom [Blossom] | 2 | 0 | EM,M,ML | 5 | Y/Y/Y | C44 | — |
| Potted Stonebark [Base] | 2 | 1 | EM,M,ML | 5 | Y/Y/Y | C44 | — |
| Potted Stonebark [Blossom] | 2 | 0 | EM,M,ML | 5 | Y/Y/Y | C44 | — |
| Preppers [Base] | 2 | 2 | EM,M,ML,L | 5 | Y/Y/Y | C26 | — |
| Preppers [Blossom] | 2 | 2 | EM,M,ML,L | 5 | Y/Y/Y | C26 | — |
| Prolific Power [Base] | 1 | 0 | ML,L,VL | 5 | Y/Y/Y | C54 | — |
| Prolific Power [Blossom] | 1 | 0 | ML,L,VL | 5 | Y/Y/Y | C54 | — |
| Propagate [Base] | 2.Rabbit | 2 | E,EM,M | 5 | Y/Y/Y | — | — |
| Propagate [Blossom] | 2.Rabbit | 1 | E,EM,M | 5 | Y/Y/Y | — | — |
| Quicken [Base] | 1 | 2 | M,ML | 5 | Y/Y/Y | C62 | — |
| Quicken [Blossom] | 1 | 2 | M,ML | 5 | Y/Y/Y | C62 | — |
| Radiantize [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Radiantize [Blossom] | 3 | 3 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Rain [Base] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Rain [Blossom] | 1 | 1 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Refreshing Light [Base] | 2 | 6 | M,ML | 5 | Y/Y/Y | C77 | — |
| Refreshing Light [Blossom] | 2 | 5 | M,ML | 5 | Y/Y/Y | C77 | — |
| Regeneration [Base] | 2 | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Regeneration [Blossom] | 2 | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Resistant [Base] | 1 | 2 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Resistant [Blossom] | 1 | 2 | ML,L,VL | 5 | Y/Y/Y | — | — |
| Revenge [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Revenge [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | — | — |
| Ride the Wave [Base] | 3 | 3 | ML,L | 5 | Y/Y/Y | C41 | — |
| Ride the Wave [Blossom] | 3 | 3 | ML,L | 5 | Y/Y/Y | C41 | — |
| Rolling Bones [Base] | 2 | 3 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Rolling Bones [Blossom] | 2 | 3 | EM,M,ML | 5 | Y/Y/Y | — | — |
| Roly-Polys [Base] | 2 | 3 | EM,M | 5 | Y/Y/Y | — | — |
| Roly-Polys [Blossom] | 2 | 3 | EM,M | 5 | Y/Y/Y | — | — |
| Salvager [Base] | 1 | 0 | ML,L | 5 | Y/Y/Y | — | Salvage Bin; Salvage Bin+; Crafted Crafting; NO SCOUT NO PIVOT |
| Salvager [Blossom] | 1 | 0 | ML,L | 5 | Y/Y/Y | — | Salvage Bin; Salvage Bin+; Crafted Crafting; NO SCOUT NO PIVOT |
| Scrappy [Base] | 2 | 3 | ML,L | 5 | Y/Y/Y | C24 | — |
| Scrappy [Blossom] | 2 | 3 | ML,L | 5 | Y/Y/Y | C27 | — |
| Search Party [Base] | 1 | 1 | M,ML | 5 | Y/Y/Y | C36 | — |
| Search Party [Blossom] | 1 | 0 | M,ML | 5 | Y/Y/Y | C36 | — |
| Sinister Deal [Base] | 2 | 0 | E,EM | 5 | Y/—/— | C59 | — |
| Sinister Deal [Blossom] | 2 | 0 | E,EM | 5 | Y/—/— | C58 | — |
| Slow Study [Base] | 2 | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Slow Study [Blossom] | 2 | 3 | M,ML | 5 | Y/Y/Y | — | — |
| Smurfing [Base] | 3 | 6 | M | 5 | Y/Y/Y | — | — |
| Smurfing [Blossom] | 3 | 5 | M | 5 | Y/Y/Y | — | — |
| Snacktime! [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C78 | — |
| Snacktime! [Blossom] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C78 | — |
| Solar Gift [Base] | 2 | 6 | E,EM | 5 | Y/Y/Y | C77 | — |
| Solitude's Cloak [Base] | 2 | 2 | L,VL | 5 | Y/Y/Y | C47 | Group Hug I; Group Hug II; Hold the Line |
| Solitude's Cloak [Blossom] | 2 | 2 | L,VL | 5 | Y/Y/Y | C47 | Group Hug I; Group Hug II; Hold the Line |
| Stand Alone [Base] | 2 | 2 | M,ML,L,VL | 5 | Y/Y/Y | C45 | — |
| Stand Alone [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Stand Alone [Blossom] | 2 | 2 | M,ML,L,VL | 5 | Y/Y/Y | C45 | — |
| Starfall [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | C11 | — |
| Starfall [Blossom] | 1 | 0 | EM,M | 5 | Y/Y/Y | C11 | — |
| Starting Town [Base] | 3 | 2 | E,EM | 5 | Y/Y/Y | — | — |
| Starting Town [Blossom] | 3 | 1 | E,EM | 5 | Y/Y/Y | — | — |
| Stealthy [Base] | 1 | 0 | ML,L | 5 | Y/Y/Y | C20 | — |
| Stealthy [Blossom] | 1 | 0 | ML,L | 5 | Y/Y/Y | C20 | — |
| Sunfire Sorcery [Base] | 1 | 2 | M,ML | 5 | Y/Y/Y | C43 | — |
| Sunfire Sorcery [Blossom] | 1 | 2 | M,ML | 5 | Y/Y/Y | C43 | — |
| Supercritical [Base] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C23 | — |
| Supercritical [Blossom] | 2 | 2 | ML,L,VL | 5 | Y/Y/Y | C23 | — |
| Take One With Ya [Base] | 1.Rabbit | 1 | E | 5 | Y/Y/— | C68 | — |
| Take One With Ya [Blossom] | 1.Rabbit | 1 | E | 5 | Y/Y/— | C68 | — |
| Tattered Armor [Base] | 1 | 1 | M,ML | 5 | Y/Y/Y | C63 | — |
| Tattered Armor [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Tattered Armor [Blossom] | 1 | 1 | M,ML | 5 | Y/Y/Y | C63 | — |
| Terraforming [Base] | 1 | 2 | ML,L,VL | 5 | Y/Y/Y | C51 | — |
| Terraforming [Blossom] | 1 | 2 | ML,L,VL | 5 | Y/Y/Y | C51 | — |
| Thingamajig Bag [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | C07 | — |
| Thingamajig Bag [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | C07 | — |
| Thingamajig Jar [Base] | 1 | 0 | E | 5 | Y/Y/Y | C07 | — |
| Thingamajig Jar [Blossom] | 1 | 1 | E | 5 | Y/Y/Y | C07 | — |
| Thingamajig Sack [Base] | 2 | 3 | L,VL | 5 | Y/Y/Y | C07 | — |
| Thingamajig Sack [Blossom] | 2 | 3 | L,VL | 5 | Y/Y/Y | C07 | — |
| Three Me [Base] | 2 | 9 | EM,M | 5 | Y/Y/Y | — | — |
| Three Me [Blossom] | 2 | 8 | EM,M | 5 | Y/Y/Y | — | — |
| Tiger's Visit [Blossom] | 2 | 2 | M,ML,L | 5 | Y/Y/Y | C80 | — |
| Tiger's Visit [Base] | 2 | 3 | M,ML,L | 5 | Y/Y/Y | C81 | — |
| Tiger's Visit [Blossom] | 2 | 2 | M,ML,L | 5 | Y/Y/Y | C81 | — |
| Training Yard [Base] | 2 | 3 | ML,L | 5 | Y/Y/Y | — | — |
| Training Yard [Blossom] | 2 | 3 | ML,L | 5 | Y/Y/Y | — | — |
| Treetop Archers [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Treetop Archers [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Treetop Archers [Blossom] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Tremors [Base] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Tremors [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Tremors [Blossom] | 3 | 3 | L,VL | 5 | Y/Y/Y | — | — |
| Trophy Hunter [Base] | 1 | 2 | E,EM,M,ML | 5 | Y/Y/Y | C75 | — |
| Trophy Hunter [Blossom] | 1 | 0 | E,EM,M,ML | 5 | Y/Y/Y | C75 | — |
| Truce [Base] | 1 | 0 | E | 5 | Y/Y/— | — | — |
| Truce [Prismatic] | 3 | 0 | E,EM,M,ML,L,VL | 5 | Y/Y/— | — | — |
| Truce [Blossom] | 1 | 0 | E | 5 | Y/Y/— | — | — |
| Turtle's Visit [Base] | 2 | 3 | M,ML,L | 5 | Y/Y/Y | C82 | — |
| Turtle's Visit [Blossom] | 2 | 2 | M,ML,L | 5 | Y/Y/Y | C82 | — |
| Ultra Ascension [Base] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Ultra Ascension [Prismatic] | 3 | 1 | E,EM,M,ML,L,VL | 5 | Y/Y/Y | — | — |
| Ultra Ascension [Blossom] | 1 | 1 | EM,M | 5 | Y/Y/Y | — | — |
| Verdant Vitality [Base] | 1 | 0 | ML,L,VL | 5 | Y/Y/Y | C54 | — |
| Verdant Vitality [Blossom] | 1 | 0 | ML,L,VL | 5 | Y/Y/Y | C54 | — |
| Wrapped In Thorns [Base] | 1 | 2 | M,ML,L,VL | 5 | Y/Y/Y | C22 | — |
| Wrapped In Thorns [Blossom] | 1 | 2 | M,ML,L,VL | 5 | Y/Y/Y | C22 | — |
| Yordle Spirit [Base] | 2 | 2 | ML,L | 5 | Y/Y/Y | — | — |
| Yordle Spirit [Blossom] | 2 | 2 | ML,L | 5 | Y/Y/Y | — | — |

</details>

#### A.1.2 Augment offer ledger

Stage flags refer to augment offering stages 2/3/4. “1P” marks the source’s one-player-per-lobby field. It is separate from mutual exclusions. The three encounter rows have no ordinary augment stage/mode flags; blank fields do not make them disabled augments. No separate disabled-entry flag was supplied by the recovered table.

Source: [LBB — augment database](https://www.littlebuddybot.com/tft-augments).

<details>
<summary>All 252 recovered augment and encounter records</summary>

| Entry | Tier | Stages | Modes | 1P | Condition | Incompatible entries |
| --- | --- | --- | --- | --- | --- | --- |
| Emblem Ensemble | Encounter | — | —/—/— | — | — | Cooking Pot; Spreading Roots; Spreading Roots+; The Trait Tree; The Trait Tree+; Branching Out; Branching Out+; Pandora's Items I; Pandora's Items II; Pandora's Items III; Coronation; Flexible; We Stick Together; U.R.F; Trait Ladder |
| Item Forge | Encounter | — | —/—/— | — | — | Forged In Strength; Latent Forge; Living Forge; Nesting Anvils; Nesting Anvils+; Portable Forge; Sweet Treats |
| Reroll Subscription | Encounter | — | —/—/— | — | — | Patience Is A Virtue; Prismatic Ticket; Rolling For Days |
| Advanced Loan | Gold | — | Y/Y/— | — | — | Advanced Loan+ |
| Advanced Loan+ | Gold | 3 | Y/Y/— | — | — | Advanced Loan |
| Arcane Viktor-y | Gold | 3,4 | Y/Y/— | — | — | — |
| Ascension | Gold | 3,4 | Y/Y/— | — | — | — |
| Augmented Power | Silver | 3 | Y/Y/— | — | — | — |
| Backline Blueprint | Gold | 2 | Y/Y/Y | — | — | — |
| Backup Bows | Silver | 2 | Y/Y/Y | — | — | Carve a Path; Extra Buckles; Flowing Tears |
| Band of Thieves | Silver | 2,3,4 | Y/Y/Y | — | — | Band of Thieves II; Band of Thieves II+; Band of Thieves II++ |
| Band of Thieves II | Prismatic | 2 | Y/Y/Y | — | — | Band of Thieves; Band of Thieves II+; Band of Thieves II++ |
| Band of Thieves II+ | Prismatic | 3 | Y/Y/— | — | — | Band of Thieves; Band of Thieves II; Band of Thieves II++ |
| Band of Thieves II++ | Prismatic | 4 | Y/Y/— | — | — | Band of Thieves; Band of Thieves II; Band of Thieves II+ |
| Baron's Lair | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Beast Within [Nidalee] | Gold | 3 | Y/Y/— | — | — | Beast Within+ [Nidalee]; Beast Within+ [Sivir]; Beast Within [Sivir] |
| Beast Within [Sivir] | Gold | 3 | Y/Y/— | — | — | Beast Within+ [Nidalee]; Beast Within+ [Sivir]; Beast Within [Nidalee] |
| Beast Within+ [Nidalee] | Gold | 4 | Y/Y/— | — | C72 | Beast Within+ [Sivir]; Beast Within [Nidalee]; Beast Within [Sivir] |
| Beast Within+ [Sivir] | Gold | 4 | Y/Y/— | — | C72 | Beast Within+ [Nidalee]; Beast Within [Nidalee]; Beast Within [Sivir] |
| Belt Overflow | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Big Grab Bag | Gold | 3,4 | Y/Y/— | — | — | — |
| Birthday Present | Prismatic | 2 | Y/Y/Y | — | — | — |
| Birthday Reunion | Gold | 2 | Y/Y/Y | — | — | — |
| Blossom's Call | Gold | 4 | Y/Y/— | — | C38 | — |
| Bodyguard Training | Gold | 2 | Y/Y/Y | — | — | — |
| Bonus Gift | Gold | 2 | Y/—/Y | — | — | Bonus Gift+; Missed Connections |
| Bonus Gift+ | Gold | 3 | Y/—/— | — | — | Bonus Gift; Missed Connections |
| Booster Pack | Gold | 2 | Y/Y/Y | — | — | — |
| Booster Pack+ | Gold | 3 | Y/Y/— | — | — | Plot Armor |
| Booster Pack++ | Gold | 4 | Y/Y/— | — | — | Plot Armor |
| Boxing Lessons | Silver | 3,4 | Y/Y/— | — | — | — |
| Branching Out | Silver | 2 | Y/Y/Y | — | — | Branching Out+ |
| Branching Out+ | Silver | 3 | Y/Y/— | — | — | Branching Out |
| Bronze For Life I | Gold | 3,4 | Y/Y/— | — | — | Bronze For Life II; Stand United; Trait Ladder |
| Bronze For Life II | Prismatic | 3,4 | Y/Y/— | — | — | Bronze For Life I; Stand United; Trait Ladder |
| Build A Bud | Prismatic | 2 | Y/Y/Y | — | — | Weight The Worth |
| Buried Treasures III | Prismatic | 2 | Y/Y/Y | — | — | Component Quest |
| Call To Chaos | Prismatic | 4 | Y/Y/— | — | — | — |
| Called Shot | Silver | 2 | Y/Y/— | — | — | — |
| Capital Gains I | Silver | 2 | Y/Y/— | — | — | — |
| Capital Gains II | Gold | 2 | Y/Y/— | — | — | — |
| Caretaker's Ally | Silver | 2 | Y/Y/Y | — | — | — |
| Caretaker's Favor | Gold | 2 | Y/Y/Y | — | — | — |
| Carve a Path | Silver | 2 | Y/Y/Y | — | — | Backup Bows; Extra Buckles; Flowing Tears |
| Celestial Blessing I | Silver | 3,4 | Y/Y/— | — | — | Celestial Blessing II; Celestial Blessing III |
| Celestial Blessing II | Gold | 3,4 | Y/Y/— | — | — | Celestial Blessing I; Celestial Blessing III |
| Celestial Blessing III | Prismatic | 3,4 | Y/Y/— | — | — | Celestial Blessing I; Celestial Blessing II |
| Challenger's Grace | Gold | 3,4 | Y/Y/— | — | — | — |
| Champ Delivery | Silver | 2 | Y/Y/Y | — | — | — |
| Champ Delivery+ | Silver | 3 | Y/Y/— | — | — | — |
| Champ Delivery++ | Silver | 4 | Y/Y/— | — | — | — |
| Chosen of the Sun | Gold | 2 | Y/Y/Y | — | — | — |
| Clear Mind | Gold | 2 | Y/—/Y | — | — | Pandora's Bench |
| Clockwork Accelerator | Gold | 3,4 | Y/Y/— | — | — | — |
| Cluttered Mind | Gold | 2 | Y/—/Y | — | — | Pandora's Bench |
| Cognitive Overload | Gold | 3 | Y/Y/— | — | — | — |
| Cognitive Tax | Silver | 2 | Y/Y/Y | — | — | Cognitive Tax+ |
| Cognitive Tax+ | Silver | 3 | Y/Y/— | — | — | Cognitive Tax |
| Comeback Story | Prismatic | 2 | Y/Y/— | — | — | — |
| Commerce Core | Prismatic | 4 | Y/Y/— | — | — | Trade Sector; Trade Sector+ |
| Component Buffet | Silver | — | Y/Y/— | — | — | — |
| Component Quest | Prismatic | 2 | Y/Y/— | — | — | Buried Treasures III |
| Consuming Flora | Gold | 2,3 | Y/Y/Y | Y | C50 | — |
| Cooking Pot | Gold | 2 | Y/Y/Y | — | — | The Trait Tree; The Trait Tree+ |
| Coronation | Prismatic | 3,4 | Y/Y/— | — | — | Trait Ladder |
| Corrosion | Silver | 3,4 | Y/Y/— | — | — | — |
| Coven Acolyte | Gold | 2 | Y/—/Y | Y | — | — |
| Crafted Crafting | Silver | 2 | Y/Y/Y | — | — | Salvage Bin; Salvage Bin+ |
| Cry Me A River | Gold | 2,3 | Y/Y/Y | — | — | Makeshift Armor I; Makeshift Armor II |
| Cybernetic Implants | Gold | 3,4 | Y/Y/— | — | — | Good For Something I |
| Cybernetic Uplink | Gold | 3,4 | Y/Y/— | — | — | — |
| Dark Ritual | Gold | 2,3 | Y/Y/Y | Y | C40 | — |
| Deadlier Blades | Prismatic | 2 | Y/Y/Y | — | — | Deadlier Caps; Retribution; Salvage Bin; Salvage Bin+; Solo Plate; Spirit Of Redemption |
| Deadlier Caps | Prismatic | 2 | Y/Y/Y | — | — | Deadlier Blades; Retribution; Salvage Bin; Salvage Bin+; Solo Plate; Spirit Of Redemption |
| Dummify | Silver | 3 | Y/Y/— | — | — | NO SCOUT NO PIVOT |
| Duo Queue | Gold | 4 | Y/Y/— | — | — | — |
| Early Learnings | Gold | 2 | Y/Y/Y | — | — | — |
| Electrocharge I | Silver | 2,3,4 | Y/Y/Y | — | — | Electrocharge II |
| Electrocharge II | Gold | 2,3,4 | Y/Y/Y | — | — | Electrocharge I |
| Embiggen | Gold | 2,3,4 | Y/Y/Y | — | C49 | — |
| Epic Rolldown | Gold | 3 | Y/Y/— | — | — | — |
| Epoch | Gold | 2 | Y/Y/— | — | — | Epoch+ |
| Epoch+ | Gold | 3 | Y/Y/— | — | — | Epoch |
| Exclusive Customization | Gold | 3,4 | Y/Y/— | — | — | — |
| Expedition | Silver | 2 | Y/—/Y | Y | — | Pandora's Bench |
| Explosive Growth | Gold | 3 | Y/Y/— | — | — | Explosive Growth+ |
| Explosive Growth+ | Gold | 4 | Y/Y/— | — | — | Explosive Growth |
| Extra Buckles | Silver | 2 | Y/Y/Y | — | — | Backup Bows; Carve a Path; Flowing Tears |
| Feeling Lucky | Silver | 3 | Y/Y/— | — | — | — |
| Find Your Center | Silver | 3,4 | Y/Y/— | — | — | — |
| Flame On | Silver | — | Y/Y/— | — | C53 | — |
| Flexible | Prismatic | 2 | Y/Y/— | — | — | Pandora's Items I; Pandora's Items II; Pandora's Items III; Salvage Bin; Salvage Bin+; The Trait Tree; The Trait Tree+ |
| Flowing Tears | Silver | 2 | Y/Y/Y | — | — | Backup Bows; Carve a Path; Extra Buckles |
| Focused Fire | Silver | 3,4 | Y/Y/— | — | — | — |
| Forged In Strength | Prismatic | 2 | Y/Y/Y | — | — | Latent Forge; Living Forge; Nesting Anvils; Nesting Anvils+; Portable Forge; Sweet Treats |
| FOURcing | Gold | 3 | Y/Y/— | — | — | — |
| Frontline Foundation | Gold | 2 | Y/Y/Y | — | — | — |
| Future Focused | Silver | 2 | Y/—/— | — | — | — |
| Gain 21 Gold | Gold | 3 | Y/Y/— | — | — | — |
| Giant and Mighty | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Gilded Steel | Gold | 4 | Y/Y/— | — | — | — |
| Glass Cannon I | Silver | 3,4 | Y/Y/— | — | — | Glass Cannon II |
| Glass Cannon II | Gold | 3,4 | Y/Y/— | — | — | Glass Cannon I |
| Going Long | Prismatic | 2 | Y/Y/Y | — | — | Invested+; Invested++ |
| Gold Destiny | Gold | 2 | Y/Y/Y | — | — | Gold Destiny+; Prismatic Destiny; Prismatic Destiny+; Silver Destiny; Silver Destiny+; Silver Destiny++ |
| Gold Destiny+ | Gold | 3 | Y/Y/— | — | — | Gold Destiny; Prismatic Destiny; Prismatic Destiny+; Silver Destiny; Silver Destiny+; Silver Destiny++ |
| Golden Gamble | Prismatic | 2 | Y/Y/Y | — | — | Golden Gamble+; Golden Gamble++ |
| Golden Gamble+ | Prismatic | 3 | Y/Y/— | — | — | Golden Gamble; Golden Gamble++ |
| Golden Gamble++ | Prismatic | 4 | Y/Y/— | — | — | — |
| Good For Something I | Silver | 2 | Y/Y/Y | — | — | Cybernetic Implants; Cybernetic Uplink |
| Group Hug I | Silver | 3,4 | Y/Y/— | — | — | — |
| Group Hug II | Gold | 3,4 | Y/Y/— | — | — | — |
| Hard Bargain | Gold | 2 | Y/—/— | — | — | — |
| Hard Commit | Prismatic | 2 | Y/Y/— | — | — | — |
| Healing Orbs I | Silver | 3,4 | Y/Y/— | — | — | — |
| Healing Orbs II | Gold | 3,4 | Y/Y/— | — | — | — |
| Heart of Steel | Gold | 2 | Y/Y/Y | — | — | Deadlier Blades; Deadlier Caps; Retribution; Salvage Bin; Salvage Bin+; Solo Plate |
| Hedge Fund | Prismatic | 2 | Y/Y/Y | — | — | Invested+; Invested++ |
| Heroic Grab Bag | Gold | 2 | Y/Y/Y | — | — | Heroic Grab Bag+; Heroic Grab Bag++ |
| Heroic Grab Bag+ | Gold | 3 | Y/Y/— | — | — | Heroic Grab Bag; Heroic Grab Bag++ |
| Heroic Grab Bag++ | Gold | 4 | Y/Y/— | — | — | Heroic Grab Bag; Heroic Grab Bag+ |
| Hold the Line | Prismatic | 3,4 | Y/Y/— | — | — | Twin Guardians |
| Hustler | Gold | 2 | Y/Y/Y | — | — | Hedge Fund; Invested+; Invested++ |
| Infinity Protection | Gold | 2 | Y/Y/— | — | — | — |
| Invested+ | Prismatic | 3 | Y/Y/— | — | — | Hedge Fund; Invested++ |
| Invested++ | Prismatic | 4 | Y/Y/— | — | — | Hedge Fund; Invested+ |
| Investment Strategy I | Gold | 2 | Y/Y/Y | — | — | Investment Strategy II |
| Investment Strategy II | Prismatic | 2 | Y/Y/Y | — | — | Investment Strategy I |
| Iron Assets | Silver | 2 | Y/Y/Y | — | — | — |
| It's Me, Baby | Gold | 3,4 | Y/Y/— | — | — | — |
| Item Extraction | Gold | 2,3 | Y/Y/Y | — | C37 | — |
| Item Grab Bag I | Silver | 2,3,4 | Y/Y/Y | — | — | — |
| Jeweled Lotus I | Gold | 3,4 | Y/Y/— | — | — | Jeweled Lotus II |
| Jeweled Lotus II | Prismatic | 3,4 | Y/Y/— | — | — | Jeweled Lotus I |
| Kick Start | Silver | 2 | Y/Y/Y | — | — | — |
| Kingslayer | Silver | 2,3 | Y/Y/— | — | — | — |
| Know Your Enemy | Gold | — | Y/Y/— | — | — | — |
| Late Game Scaling | Gold | 2 | Y/Y/Y | — | — | — |
| Late Game Specialist | Silver | 3 | Y/Y/— | — | — | Level Up! |
| Latent Forge | Silver | 2 | Y/Y/Y | — | — | Forged In Strength; Living Forge; Nesting Anvils; Nesting Anvils+; Portable Forge; Sweet Treats |
| Legion Of Threes | Gold | 2 | Y/Y/Y | — | — | — |
| Level Up! | Prismatic | 2 | Y/Y/Y | — | — | Late Game Specialist |
| Living Forge | Prismatic | 2 | Y/Y/Y | — | — | — |
| Loaded Dice | Silver | 2 | Y/Y/Y | — | — | — |
| Lucky Gloves | Prismatic | 2 | Y/Y/Y | — | — | Lucky Gloves+; Makeshift Armor I; Makeshift Armor II |
| Lucky Gloves+ | Prismatic | 3,4 | Y/Y/— | — | — | Lucky Gloves; Makeshift Armor I; Makeshift Armor II |
| Luxury Subscription | Prismatic | 3 | Y/Y/— | — | — | — |
| Magic Roll | Gold | 3 | Y/Y/— | — | — | — |
| Makeshift Armor I | Silver | 2,3 | Y/Y/Y | — | C85 | Cybernetic Implants; Cybernetic Uplink; Lucky Gloves; Lucky Gloves+; Makeshift Armor II |
| Makeshift Armor II | Gold | 2,3 | Y/Y/Y | — | C85 | Cybernetic Implants; Cybernetic Uplink; Lucky Gloves; Lucky Gloves+; Makeshift Armor I |
| Malicious Monetization | Gold | 4 | Y/Y/— | — | — | — |
| Master of All Origins | Prismatic | 4 | Y/Y/— | — | C71 | — |
| Max Build | Gold | 4 | Y/Y/— | — | — | One Buff Two Buff |
| Min-Max | Prismatic | 3 | Y/Y/— | — | — | — |
| Missed Connections | Silver | 3,4 | Y/Y/— | — | — | — |
| Money Hungry | Gold | 2 | Y/Y/Y | — | — | Money Hungry+ |
| Money Hungry+ | Gold | 3 | Y/Y/— | — | — | Money Hungry |
| Money Monsoon | Prismatic | 4 | Y/Y/— | — | — | — |
| Nature's Shelter | Gold | 2,3,4 | Y/Y/Y | — | C46 | — |
| Nesting Anvils | Prismatic | 3 | Y/Y/— | — | — | Forged In Strength; Latent Forge; Living Forge; Nesting Anvils+; Portable Forge; Sweet Treats |
| Nesting Anvils+ | Prismatic | 4 | Y/Y/— | — | — | Forged In Strength; Latent Forge; Living Forge; Nesting Anvils; Portable Forge; Sweet Treats |
| Nesting Dolls [+] | Prismatic | 3 | Y/Y/— | — | C83 | Nesting Dolls [++] |
| Nesting Dolls [++] | Prismatic | 4 | Y/Y/— | — | C83 | — |
| NO SCOUT NO PIVOT | Gold | 2 | Y/—/Y | — | — | Dummify; Recombobulator |
| Omega Riftbeast | Gold | 2,3,4 | Y/Y/Y | — | C74 | — |
| One Buff Two Buff | Prismatic | 3,4 | Y/Y/— | — | — | Max Build |
| One, Two, Five! | Silver | 4 | Y/Y/— | — | — | — |
| Ones Two Three | Silver | 2 | Y/Y/Y | — | — | — |
| Pandora's Bench | Silver | 2,3 | Y/—/Y | — | — | Clear Mind; Cluttered Mind |
| Pandora's Items I | Silver | 2,3,4 | Y/Y/Y | — | — | Flexible; Pandora's Items II; Pandora's Items III; Slammin'; Slammin'+ |
| Pandora's Items II | Gold | 2,3,4 | Y/Y/Y | — | — | Flexible; Pandora's Items I; Pandora's Items III; Slammin'; Slammin'+ |
| Pandora's Items III | Prismatic | 2,3 | Y/Y/Y | — | — | Flexible; Pandora's Items I; Pandora's Items II; Slammin'; Slammin'+ |
| Partial Ascension | Silver | 3,4 | Y/Y/— | — | — | — |
| Patience Is A Virtue | Silver | 2 | Y/Y/Y | — | — | — |
| Patient Study | Gold | 2 | Y/Y/Y | — | — | — |
| Pilfer | Gold | 3 | Y/Y/— | — | — | — |
| Plot Armor | Gold | 3,4 | Y/Y/— | — | — | — |
| Portable Forge | Gold | 2,3,4 | Y/Y/Y | — | — | Forged In Strength; Latent Forge; Living Forge; Nesting Anvils; Nesting Anvils+; Sweet Treats |
| Prismatic Destiny | Prismatic | 2 | Y/Y/Y | — | — | Gold Destiny; Gold Destiny+; Prismatic Destiny+; Silver Destiny; Silver Destiny+; Silver Destiny++ |
| Prismatic Destiny+ | Prismatic | 3 | Y/Y/— | — | — | Gold Destiny; Gold Destiny+; Prismatic Destiny; Silver Destiny; Silver Destiny+; Silver Destiny++ |
| Prismatic Ticket | Prismatic | 2,3 | Y/Y/Y | — | — | — |
| Promised Protection | Gold | 2,3 | Y/Y/Y | — | — | Makeshift Armor I; Makeshift Armor II |
| Quick Streaks | Silver | 2 | Y/Y/— | — | — | — |
| Radiant Rascal | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Radiant Relics | Prismatic | 2,3,4 | Y/Y/Y | — | — | — |
| Recombobulator | Silver | 3 | Y/Y/— | — | — | — |
| Replication | Gold | 2,3 | Y/Y/Y | — | — | — |
| Residual Magic | Silver | 2 | Y/Y/Y | — | — | Residual Magic +; Residual Magic ++ |
| Residual Magic + | Silver | 3 | Y/Y/— | — | — | Residual Magic; Residual Magic ++ |
| Residual Magic ++ | Silver | 4 | Y/Y/— | — | — | Residual Magic; Residual Magic + |
| Retribution | Prismatic | 3,4 | Y/Y/— | — | — | Deadlier Blades; Deadlier Caps; Solo Plate; Spirit Of Redemption |
| Rolling For Days | Silver | 3,4 | Y/Y/— | — | — | — |
| Salvage Bin | Gold | 2 | Y/Y/Y | — | — | Crafted Crafting; Flexible; Salvage Bin+ |
| Salvage Bin+ | Gold | 3,4 | Y/Y/— | — | — | Crafted Crafting; Flexible; Salvage Bin |
| Seraphim's Staff | Gold | 2,3 | Y/Y/Y | — | — | Deadlier Blades; Deadlier Caps; Retribution; Solo Plate; Spirit Of Redemption |
| Shimmerscale Essence | Prismatic | 2 | Y/Y/Y | — | — | — |
| Shopping Spree | Prismatic | 2 | Y/Y/Y | — | — | Trade Sector; Trade Sector+ |
| Silver Destiny | Silver | 2 | Y/Y/Y | — | — | Gold Destiny; Gold Destiny+; Prismatic Destiny; Prismatic Destiny+; Silver Destiny+; Silver Destiny++ |
| Silver Destiny+ | Silver | 3 | Y/Y/— | — | — | Gold Destiny; Gold Destiny+; Prismatic Destiny; Prismatic Destiny+; Silver Destiny; Silver Destiny++ |
| Silver Destiny++ | Silver | 4 | Y/Y/— | — | — | Gold Destiny; Gold Destiny+; Prismatic Destiny; Prismatic Destiny+; Silver Destiny; Silver Destiny+ |
| Silver Spoon | Silver | 2 | Y/Y/Y | — | — | — |
| Slammin' | Gold | 2 | Y/—/Y | — | — | Pandora's Items I; Pandora's Items II; Pandora's Items III; Slammin'+ |
| Slammin'+ | Gold | 3 | Y/—/— | — | — | Pandora's Items I; Pandora's Items II; Pandora's Items III; Slammin' |
| Slice of Life | Silver | 2 | Y/Y/— | — | — | — |
| Slightly Magic Roll | Silver | 2 | Y/Y/Y | — | — | — |
| Small Furry Friend | Gold | 2,3,4 | Y/Y/Y | — | C79 | — |
| Small Grab Bag | Silver | 3,4 | Y/Y/— | — | — | — |
| Solo Leveling | Gold | 2 | Y/Y/— | — | — | — |
| Solo Plate | Gold | 2,3 | Y/Y/Y | — | — | Deadlier Blades; Deadlier Caps; Retribution; Spirit Of Redemption; Twin Guardians |
| Soul Awakening | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Speedy Double Kill | Gold | 2 | Y/—/— | — | — | — |
| Spirit Of Redemption | Gold | 2,3 | Y/Y/Y | — | — | Deadlier Blades; Deadlier Caps; Retribution; Solo Plate |
| Spreading Roots | Gold | 2 | Y/Y/Y | — | — | Cooking Pot; Spreading Roots+; Trait Ladder |
| Spreading Roots+ | Gold | 3 | Y/Y/— | — | — | Cooking Pot; Spreading Roots; Trait Ladder |
| Staffsmith | Gold | 4 | Y/Y/— | — | — | — |
| Stand United | Silver | 3,4 | Y/Y/— | — | — | Bronze For Life I; Bronze For Life II |
| Sun and Moon | Gold | 3 | Y/Y/— | — | C84 | Sun and Moon+ |
| Sun and Moon+ | Gold | 4 | Y/Y/— | — | C87 | Sun and Moon |
| Sweet Treats | Prismatic | 3,4 | Y/Y/— | — | — | Forged In Strength; Latent Forge; Living Forge; Nesting Anvils; Nesting Anvils+; Portable Forge |
| Sword Overflow | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Swordsmith | Gold | 4 | Y/Y/— | — | — | — |
| Tactician's Kitchen | Prismatic | 2 | Y/Y/Y | — | — | Coronation |
| Team Building | Silver | 2,3 | Y/Y/Y | — | — | — |
| The Golden Dragon | Gold | 3 | Y/Y/— | — | — | — |
| The Golden Egg | Prismatic | 4 | Y/Y/— | — | C86 | — |
| The Tower | Silver | 2,3,4 | Y/Y/Y | — | — | — |
| The Trait Tree | Prismatic | 2 | Y/Y/Y | — | — | Cooking Pot; The Trait Tree+; Trait Ladder |
| The Trait Tree+ | Prismatic | 3 | Y/Y/— | — | — | Cooking Pot; Flexible; The Trait Tree; Trait Ladder |
| Time Skip | Gold | 2 | Y/Y/— | — | — | — |
| Tons of Stats! | Gold | 3,4 | Y/Y/— | — | — | — |
| TONS of Stats! | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Trade Sector | Gold | 2 | Y/Y/Y | — | — | Commerce Core; Trade Sector+ |
| Trade Sector+ | Gold | 3 | Y/Y/— | — | — | Commerce Core; Trade Sector |
| Trait Ladder | Prismatic | 2 | Y/Y/Y | Y | — | Bronze For Life I; Bronze For Life II; Coronation; Spreading Roots; Spreading Roots+; The Trait Tree; The Trait Tree+; Verticality I; Verticality II; Verticality III |
| Twin Guardians | Silver | 3,4 | Y/Y/— | — | — | Hold the Line; Solo Plate |
| U.R.F | Gold | 2,3,4 | Y/Y/Y | — | — | — |
| Unrivaled | Gold | 2,3 | Y/Y/Y | Y | C76 | — |
| Upward Mobility | Prismatic | 2 | Y/—/Y | — | — | — |
| Urf's Grab Bag | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Verticality I | Silver | 3,4 | Y/Y/— | — | — | Trait Ladder |
| Verticality II | Gold | 3,4 | Y/Y/— | — | — | Trait Ladder |
| Verticality III | Prismatic | 3,4 | Y/Y/— | — | — | Trait Ladder |
| Wand Overflow | Prismatic | 3,4 | Y/Y/— | — | — | — |
| Warpath | Gold | 2 | Y/—/— | — | — | — |
| We Stick Together | Prismatic | 2 | Y/Y/Y | — | — | — |
| Weight The Worth | Gold | 3 | Y/Y/— | — | C83 | Build A Bud |
| Wisp Rebate | Silver | 3 | Y/Y/— | — | — | Wisp Rebate+ |
| Wisp Rebate+ | Silver | 4 | Y/Y/— | — | — | Wisp Rebate |
| Worth the Wait | Gold | 2 | Y/Y/Y | — | — | Weight The Worth |
| Worth the Wait II | Prismatic | 2 | Y/Y/Y | — | — | Weight The Worth; Worth the Wait |
| Woven Magic | Gold | 2 | Y/Y/Y | — | — | — |
| Young and Wild and Free | Silver | 2 | Y/Y/— | — | — | — |

</details>

<details>
<summary>Requirement key for both offer ledgers</summary>

Conditions preserve distinctions such as board versus army, exact counts versus minimums, and AND versus OR. “Itemized” remains the source’s term; no minimum item count is inferred unless explicitly stated.

| Key | Published requirement |
| --- | --- |
| C01 | A 1-cost champion in your army. Can only be offered in the first 3 seconds of planning phase. |
| C02 | A 1-cost or 2-cost champion at 2 stars or higher on your board or bench. |
| C03 | A 2-cost champion in your army. Can only be offered in the first 3 seconds of planning phase. |
| C04 | A 4-cost champion in your army. Can only be offered in the first 3 seconds of planning phase. |
| C05 | An itemized champion on your board with the Attack damage category and a role of Assassin, Caster, Marksman, Fighter or Specialist. |
| C06 | An itemized champion on your board with the Fighter role; at least 2 Fighters on the board. |
| C07 | An itemized champion on your board with the Magic damage category and a role of Caster, Fighter, Marksman or Assassin. |
| C08 | An itemized champion on your board with the Tank role. |
| C09 | At least 1 champion on your bench. |
| C10 | At least 1 item components on your bench. |
| C11 | At least 10 gold. |
| C12 | At least 10 player health missing. |
| C13 | At least 12 gold. |
| C14 | At least 15 gold. |
| C15 | At least 2 1-star champions on the board, OR a 1-star 5-cost champion holding 3 items. |
| C16 | At least 2 1-star champions on your board. |
| C17 | At least 2 Casters on the board. |
| C18 | At least 2 Casters on the board; an itemized champion on your board with the Caster role. |
| C19 | At least 2 Fighters on the board; an itemized Fighter champion on your board. |
| C20 | At least 2 Fighters or Assassins on the board; an itemized champion on your board with a role of Assassin or Fighter. |
| C21 | At least 2 Marksmans on the board; an itemized champion on your board with the Marksman role. |
| C22 | At least 2 Tanks on the board. |
| C23 | At least 2 champions anywhere in your army that can critically strike with abilities. |
| C24 | At least 2 champions on your board with no items. |
| C25 | At least 2 inactive traits (contributed but not active). |
| C26 | At least 2 stacking items in your army. |
| C27 | At least 3 champions on your board with no items. |
| C28 | At least 3 item components, including completed items (counts as 2 components). |
| C29 | At least 30 gold. |
| C30 | At least 35 gold; more than 50 player health remaining; level 10 or higher. |
| C31 | At least 4 inactive traits (contributed but not active). |
| C32 | At least 5 active non-unique traits. |
| C33 | At least 5 champions on your board each holding 1 or more items; Elderwood not active. |
| C34 | At least 5 gold. |
| C35 | At least 70 player health missing. |
| C36 | At least 8 gold. |
| C37 | Blackthorn to be active. |
| C38 | Blossom to be active. |
| C39 | Coven active. |
| C40 | Coven to be active. |
| C41 | During the shop phase, only in the first 20 seconds; at least 20 gold. |
| C42 | During the shop phase, only in the first 8 seconds. |
| C43 | Either no Morellonomicon, Sunfire Cape or Red Buff (base or Radiant), or Inferno active. |
| C44 | Elderwood active. |
| C45 | Elderwood not active; Lunar not active; Greenfather not active. |
| C46 | Elderwood to be active. |
| C47 | Elderwood, Lunar and Greenfather all inactive. |
| C48 | Exactly 2 or 3 (no more or less) champions holding 3 items each. |
| C49 | Fae to be active. |
| C50 | Flora Fatalis to be active. |
| C51 | Greenfather active. |
| C52 | Inferno active. |
| C53 | Inferno at Silver tier or higher. |
| C54 | Less than 10 gold. |
| C55 | Lunar active. |
| C56 | More than 1 player health remaining. |
| C57 | More than 10 player health remaining. |
| C58 | More than 3 player health remaining. |
| C59 | More than 4 player health remaining. |
| C60 | More than 8 player health remaining. |
| C61 | No 3-star champion in your army; not on a win streak of 3 or more. |
| C62 | Not offered when a manaless champion on the board holds 3 items. |
| C63 | Not offered while you hold Last Whisper, Void Staff, Ionic Spark or Evenshroud (base or Radiant). |
| C64 | Not offered while you hold Last Whisper, Void Staff, Ionic Spark or Evenshroud (base or Radiant); either no Morellonomicon, Sunfire Cape or Red Buff (base or Radiant), or Inferno active. |
| C65 | Not on a loss streak of 3 or more. |
| C66 | Not on a loss streak of 3 or more; Coven not active. |
| C67 | Not on a loss streak. |
| C68 | Not on a win streak of 3 or more. |
| C69 | On a win streak (any length). |
| C70 | On no streak or a loss streak (any length). |
| C71 | Only offered if you do not own Avatar. |
| C72 | Primal to be active. |
| C73 | Riftbeast active. |
| C74 | Riftbeast to be active. |
| C75 | Rival active. |
| C76 | Rival to be active. |
| C77 | Solar active. |
| C78 | Sprykin active. |
| C79 | Sprykin to be active. |
| C80 | You have not already taken the Bear Primal blessing; Primal active. |
| C81 | You have not already taken the Tiger Primal blessing; Primal active. |
| C82 | You have not already taken the Turtle Primal blessing; Primal active. |
| C83 | at least 1 champion with 7 copies. |
| C84 | at least 3 champions with Lunar or Solar. |
| C85 | at least 4 champions without items. |
| C86 | at least 40 Tactician Health. |
| C87 | either Solar or Lunar to be active. |

</details>

#### A.1.3 Bonus Gift source ledger

Orb = qualifying orb delivery; Non-Orb = does not trigger this opening-based effect; Conditional = depends on the stated delivery/bench condition; Mixed = only part of the reward is an orb. Counts describe orbs, not the number of objects inside them. “Base” and “Blossom” distinguish Wisp variants only; other rows retain their source names.

Source: [LBB — Bonus Gift sources](https://www.littlebuddybot.com/tft-bonus-gift).

<details>
<summary>All 267 recovered Bonus Gift classification records</summary>

| Source / variant | Type | Class | Orb count | Appearance | Delivery rule |
| --- | --- | --- | --- | --- | --- |
| Apprentice [Base] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Apprentice [Blossom] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Artifactinate [Base] | Wisp | Conditional | 0–1 | Stage 2-1 to 3-4 | Artifact Anvil becomes an orb only if the unit bench is full. |
| Artifactinate [Blossom] | Wisp | Conditional | 0–2 | Stage 2-1 to 3-4 | Artifact Anvil becomes an orb if the unit bench is full; Reforger if the item bench is full. |
| Backline Blueprint | Augment | Orb | 1 | Stage 2 | — |
| Backup Bows | Augment | Orb | 3 | Stage 2 | Immediate: 1 Bow orb. Delayed: 2 after 1,000 attacks. |
| Band of Thieves | Augment | Orb | 1 | Stage 2/Stage 3/Stage 4 | — |
| Band of Thieves II | Augment | Orb | 2 | Stage 2 | Immediate: 1 orb containing 2 Thief's Gloves. Delayed: 1 Thief's Gloves orb after 5 player combats. |
| Band of Thieves II+ | Augment | Orb | 2 | Stage 3 | Immediate: 1 orb containing 2 Thief's Gloves. Delayed: 1 Thief's Gloves orb after 5 player combats. |
| Band of Thieves II++ | Augment | Orb | 2 | Stage 4 | Immediate: 1 orb containing 2 Thief's Gloves. Delayed: 1 Thief's Gloves orb after 3 player combats. |
| Baron's Lair | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Beast Within [Nidalee] | Augment | Non-Orb | 0 | Stage 3 | — |
| Beast Within [Sivir] | Augment | Non-Orb | 0 | Stage 3 | — |
| Beast Within+ [Nidalee] | Augment | Non-Orb | 0 | Stage 4 | — |
| Beast Within+ [Sivir] | Augment | Non-Orb | 0 | Stage 4 | — |
| Belt Overflow | Augment | Orb | 4 | Stage 3/Stage 4 | — |
| Big Grab Bag | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Big Guns [Base] | Wisp | Orb | 1 | Stage 4-2 to 4-7 | — |
| Big Guns [Blossom] | Wisp | Orb | 1 | Stage 4-2 to 4-7 | — |
| Birthday Present | Augment | Orb | Varies | Stage 2 | Immediate: 0 orbs. Delayed: 1 champion orb per later level-up. |
| Birthday Reunion | Augment | Mixed | 1 | Stage 2 | Component is an orb; both champions go to the unit bench or board overflow. |
| Blast Potion [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Blast Potion [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Blood and Iron [Base] | Wisp | Orb | 1 | Stage 3-1 to 4-1 | Immediate: 0 orbs. Delayed: 1 component anvil orb after 20 champion deaths. |
| Blood and Iron [Blossom] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | Immediate: 0 orbs. Delayed: 1 component anvil orb after 20 champion deaths. |
| Blood Ritual [Base] | Wisp | Non-Orb | 0 | Stage 4-2 to 4-7 | — |
| Blood Ritual [Blossom] | Wisp | Non-Orb | 0 | Stage 4-2 to 4-7 | — |
| Blossom's Call | Augment | Non-Orb | 0 | Stage 4 | — |
| Booster Pack | Augment | Orb | 3–6 | Stage 2 | 1 orb per champion from each pack. |
| Booster Pack+ | Augment | Orb | 4–6 | Stage 3 | 1 orb per champion from each pack. |
| Booster Pack++ | Augment | Orb | 3–6 | Stage 4 | 1 orb per champion from each pack. |
| Borrowed Gear [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Borrowed Gear [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Branching Out | Augment | Orb | 1 | Stage 2 | — |
| Branching Out+ | Augment | Orb | 1 | Stage 3 | — |
| Build A Bud | Augment | Orb | 1 | Stage 2 | — |
| Bunch-o'-Belts [Base] | Wisp | Non-Orb | 0 | Stage 3-5 to 4-7 | — |
| Bunch-o'-Belts [Blossom] | Wisp | Non-Orb | 0 | Stage 3-5 to 4-7 | — |
| Buried Treasures III | Augment | Orb | 7 | Stage 2 | Immediate: 1 component orb. Delayed: 1 in each of the next 6 rounds. |
| Call To Chaos | Augment | Orb | 0–2 | Stage 4 | 33% chance of a cashout with 0 orbs; all other cashouts give 1 immediate bundled orb; Golden Egg reward also gives 1 delayed orb when egg hatches. |
| Caretaker's Ally | Augment | Conditional | Varies | Stage 2 | Immediate: 1 champion; later: 1 per level. Each becomes an orb only if the unit bench is full. |
| Caretaker's Favor | Augment | Orb | 4 | Stage 2 | Immediate: 0. Delayed: 1 anvil orb at each of levels 5–8. |
| Carve a Path | Augment | Orb | 3 | Stage 2 | Immediate: 1 Sword orb. Delayed: 2 after 65,000 physical damage. |
| Champ Delivery | Augment | Orb | 6 | Stage 2 | Immediate: 3 champion orbs. Delayed: 3 after 6 rounds. |
| Champ Delivery+ | Augment | Orb | 6 | Stage 3 | Immediate: 3 champion orbs. Delayed: 3 after 6 rounds. |
| Champ Delivery++ | Augment | Orb | 6 | Stage 4 | Immediate: 3 champion orbs. Delayed: 3 after 6 rounds. |
| Chosen of the Sun | Augment | Non-Orb | 0 | Stage 2 | — |
| Circle of Elders [Base] | Wisp | Orb | 10 | Stage 6-1 to 10-1 | 1 orb per 5-cost champion. |
| Circle of Elders [Blossom] | Wisp | Orb | 10 | Stage 6-1 to 10-1 | 1 orb per 5-cost champion. |
| Cluttered Mind | Augment | Orb | 1 | Stage 2 | — |
| Cognitive Overload | Augment | Orb | 4 | Stage 3 | — |
| Component Bounty [Base] | Wisp | Orb | 1 | Stage 3-1 to 4-7 | Immediate: 0 orbs. Delayed: 1 component orb if you win the next player combat. |
| Component Bounty [Blossom] | Wisp | Orb | 1 | Stage 3-1 to 4-7 | Immediate: 0 orbs. Delayed: 1 component orb if you win the next player combat. |
| Component Quest | Augment | Orb | 8 | Stage 2 | Immediate: 1 component orb. Delayed: 1 after each of the next 7 wins. |
| Consuming Flora | Augment | Orb | 1 | Stage 2 | — |
| Consuming Flora | Augment | Orb | 1 | Stage 3 | — |
| Cooking Pot | Augment | Orb | 1 | Stage 2 | — |
| Coronation | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Coven Acolyte | Augment | Non-Orb | 0 | Stage 2 | — |
| Coven cashouts | Trait | Orb | Varies | Trait mechanic | 1 orb per reward element. |
| Cry Me A River | Augment | Orb | 1 | Stage 2/Stage 3 | — |
| Curio Cart [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Curio Cart [Blossom] | Wisp | Non-Orb | 0 | Stage 3-5 to 5-7 | — |
| Cybernetic Implants | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Cybernetic Uplink | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Dark Ritual | Augment | Non-Orb | 0 | Stage 2/Stage 3 | — |
| Deadlier Blades | Augment | Orb | 1 | Stage 2 | — |
| Deadlier Caps | Augment | Orb | 1 | Stage 2 | — |
| Doodad Bag [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-1 | — |
| Doodad Bag [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-1 | — |
| Doodad Jar [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Doodad Jar [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Doodad Sack [Base] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Doodad Sack [Blossom] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Draven, Bounty Seeker | Champion | Orb | 1 | Champion mechanic | 1 B.F. Sword orb. |
| Dummify | Augment | Mixed | 1 | Stage 3 | 1 champion orb; Training Dummy goes directly to the board. |
| Duo Queue | Augment | Orb | 4 | Stage 4 | 2 champion orbs and 2 component orbs. |
| Early Fix [Base] | Wisp | Conditional | 0–1 | Stage 2-1 to 2-7 | Reforger becomes an orb only if the item bench is full. |
| Early Fix [Blossom] | Wisp | Conditional | 0–2 | Stage 2-1 to 2-7 | Each Reforger becomes an orb only if the item bench is full. |
| Embiggen | Augment | Non-Orb | 0 | Stage 2/Stage 3/Stage 4 | — |
| Exclusive Customization | Augment | Orb | 2 | Stage 3/Stage 4 | — |
| Expedition | Augment | Orb | 2 | Stage 2 | Immediate: 1 champion orb. Delayed: 1 bundled cashout orb. |
| Extra Buckles | Augment | Orb | 3 | Stage 2 | Immediate: 1 Belt orb. Delayed: 2 after taking 75,000 damage. |
| Fae Golden Pixies | Trait | Non-Orb | 0 | Trait mechanic | Loose gold. |
| Field of Mice [Base] | Wisp | Orb | 2+ | Stage 3-1 to 4-1 | 1 per unique 1-cost fielded. |
| Field of Mice [Blossom] | Wisp | Orb | 2+ | Stage 3-1 to 4-1 | 1 per unique 1-cost fielded. Upgrade gold is not an orb. |
| Flexible | Augment | Orb | 1+ | Stage 2 | Immediate: 1 Emblem orb. Delayed: 1 at each later stage start. |
| Flowing Tears | Augment | Orb | 3 | Stage 2 | Immediate: 1 Tear orb. Delayed: 2 after spending 6,500 Mana. |
| Forest Guide [Base] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Forest Guide [Blossom] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Forest Twins [Base] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Forest Twins [Blossom] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Forged In Strength | Augment | Orb | 5 | Stage 2 | Immediate: 1 Artifact orb. Delayed cashout: 4 separate orbs. |
| Found Friend [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Found Friend [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| FOURcing | Augment | Orb | 1 | Stage 3 | — |
| Frontline Foundation | Augment | Orb | 1 | Stage 2 | — |
| Future Focused | Augment | Orb | 3 | Stage 2 | Immediate: 0 orbs; Health is lost now. Delayed: 3 champion orbs after 5 player combats; gold is loose. |
| Gilded Steel | Augment | Orb | 2 | Stage 4 | — |
| Golden Gamble | Augment | Orb | 1 | Stage 2 | — |
| Golden Gamble+ | Augment | Orb | 1 | Stage 3 | — |
| Golden Gamble++ | Augment | Orb | 1 | Stage 4 | — |
| Grandmaster [Base] | Wisp | Orb | 1 | Stage 6-1 to 10-1 | — |
| Grandmaster [Blossom] | Wisp | Orb | 1 | Stage 6-1 to 10-1 | — |
| Greater Chaos [Base] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Greater Chaos [Blossom] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Hard Bargain | Augment | Non-Orb | 0 | Stage 2 | — |
| Hard Commit | Augment | Conditional | Varies | Stage 2 | Immediate: Emblem becomes an orb if the item bench is full; champion if the unit bench is full. Later: 1 champion per stage, orb only if the unit bench is full. |
| Health Potion [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Health Potion [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Heart of Steel | Augment | Orb | 1 | Stage 2 | — |
| Heated Rivalry [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Heated Rivalry [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Hero Of Prophecy [Base] | Wisp | Non-Orb | 0 | Stage 6-1 to 10-1 | — |
| Hero Of Prophecy [Blossom] | Wisp | Non-Orb | 0 | Stage 6-1 to 10-1 | — |
| Hero's Entrance [Base] | Wisp | Non-Orb | 0 | Stage 6-1 to 10-1 | — |
| Hero's Entrance [Blossom] | Wisp | Non-Orb | 0 | Stage 6-1 to 10-1 | — |
| Heroic Grab Bag | Augment | Orb | 2 | Stage 2 | — |
| Heroic Grab Bag+ | Augment | Orb | 2 | Stage 3 | — |
| Heroic Grab Bag++ | Augment | Orb | 2 | Stage 4 | — |
| Hireling [Base] | Wisp | Non-Orb | 0 | Stage 6-1 to 10-1 | — |
| Hireling [Prismatic] | Wisp | Non-Orb | 0 | Stage 2-1 to 10-1 | — |
| Hireling [Blossom] | Wisp | Non-Orb | 0 | Stage 6-1 to 10-1 | — |
| Infinity Protection | Augment | Orb | 1 | Stage 2 | Immediate: 0 orbs; gold is loose. Delayed: 1 Infinity Force orb on Stage 3-7. |
| Iron Assets | Augment | Orb | 1 | Stage 2 | — |
| Item Extraction | Augment | Mixed | 4 | Stage 2/Stage 3 | 1 orb per component; Veigar and Rek'Sai go to the unit bench. |
| Item Grab Bag I | Augment | Orb | 1 | Stage 2/Stage 3/Stage 4 | — |
| Journeyman [Base] | Wisp | Orb | 1 | Stage 2-1 to 3-4 | — |
| Journeyman [Blossom] | Wisp | Orb | 1 | Stage 2-1 to 3-4 | — |
| Kick Start | Augment | Orb | 1 | Stage 2 | — |
| Knick-Knack Bag [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-1 | — |
| Knick-Knack Bag [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-1 | — |
| Knick-Knack Jar [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Knick-Knack Jar [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Knick-Knack Sack [Base] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Knick-Knack Sack [Blossom] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Late Bloomer [Base] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Late Bloomer [Prismatic] | Wisp | Non-Orb | 0 | Stage 2-1 to 10-1 | — |
| Late Bloomer [Blossom] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Latent Forge | Augment | Orb | 1 | Stage 2 | Immediate: 0. Delayed: 1 Artifact Anvil orb. |
| LeBlanc, Mirror Image | Champion | Non-Orb | 0 | Champion mechanic | Copy goes to the bench and overflows to the board. |
| Legion Of Threes | Augment | Non-Orb | 0 | Stage 2 | — |
| Lesser Chaos [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 3-4 | — |
| Lesser Chaos [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 3-4 | — |
| Living Forge | Augment | Orb | 1+ | Stage 2 | Immediate: 1 Artifact Anvil orb. Delayed: 1 every 10 player combats. |
| Loaded Dice | Augment | Non-Orb | 0 | Stage 2 | Loose gold coins; not eligible. |
| Lost Travelers [Base] | Wisp | Conditional | 0–3 | Stage 2-1 to 2-7 | Each champion becomes an orb only if the unit bench is full. |
| Lost Travelers [Blossom] | Wisp | Conditional | 0–4 | Stage 2-1 to 2-7 | Each champion becomes an orb only if the unit bench is full. |
| Lucky Gloves | Augment | Orb | 2 | Stage 2 | — |
| Lucky Gloves+ | Augment | Orb | 3 | Stage 3/Stage 4 | Immediate: 2 Sparring Gloves orbs. Delayed: 1 orb after 4 player combats. |
| Luxury Subscription | Augment | Orb | 6 | Stage 3 | Immediate: 2 champion orbs. Delayed: 2 orbs at the start of the next 2 stages. |
| Magic Roll | Augment | Orb | 0–1 | Stage 3 | 25% chance of Hugeify (0 orbs); all other rewards give 1 bundled orb. |
| Mana Potion [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Mana Potion [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Master of All Origins | Augment | Mixed | 1 | Stage 4 | 1 Spear of Shojin orb; Lux goes to the unit bench. |
| Max Build | Augment | Orb | 1 | Stage 4 | Immediate: 0 orbs. Delayed: 1 Duplicator orb at level 9. |
| Min-Max | Augment | Orb | 5 | Stage 3 | — |
| Minor Blood Ritual [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 3-4 | — |
| Minor Blood Ritual [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 3-4 | — |
| Missed Connections | Augment | Orb | 14 | Stage 3/Stage 4 | 1 orb per 1-cost champion. |
| Mitosis [Base] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Mitosis [Blossom] | Wisp | Orb | 1 | Stage 2-1 to 2-7 | — |
| Nature's Ally [Base] | Wisp | Non-Orb | 0 | Stage 4-2 to 10-1 | — |
| Nature's Ally [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 3-4; Stage 4-2 to 4-7 | — |
| Nature's Shelter | Augment | Non-Orb | 0 | Stage 2/Stage 3/Stage 4 | — |
| Nesting Anvils | Augment | Orb | 1 | Stage 3 | 1 Artifact Anvil orb. The Component Anvil is added directly to the freed bench slot. |
| Nesting Anvils+ | Augment | Orb | 1 | Stage 4 | 1 Artifact Anvil orb. The Component Anvil is added directly to the freed bench slot. |
| Nesting Dolls [+] | Augment | Non-Orb | 0 | Stage 3 | — |
| Nesting Dolls [++] | Augment | Non-Orb | 0 | Stage 4 | — |
| Omega Riftbeast | Augment | Non-Orb | 0 | Stage 2/Stage 3/Stage 4 | — |
| One Buff Two Buff | Augment | Orb | 3 | Stage 3/Stage 4 | — |
| One, Two, Five! | Augment | Orb | 2 | Stage 4 | — |
| Ones Two Three | Augment | Orb | 4 | Stage 2 | — |
| Ornn passive | Champion | Orb | Varies | Champion mechanic | Immediate: 0. Delayed: 1 orb per completed craft. |
| Pandora's Items I | Augment | Orb | 1 | Stage 2/Stage 3/Stage 4 | — |
| Pandora's Items II | Augment | Orb | 2 | Stage 2/Stage 3/Stage 4 | — |
| Pandora's Items III | Augment | Orb | 1 | Stage 2/Stage 3 | — |
| Peddler [Base] | Wisp | Conditional | 0–1 | Stage 4-2 to 5-7 | 0 orbs for Reforger; 1 orb for any other armory choice. |
| Peddler [Blossom] | Wisp | Conditional | 0–1 | Stage 4-2 to 5-7 | 0 orbs for Reforger; 1 orb for any other armory choice. |
| Petrified Dummy [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Petrified Dummy [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Phantom Armor [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 5-7 | — |
| Phantom Armor [Prismatic] | Wisp | Non-Orb | 0 | Stage 2-1 to 10-1 | — |
| Phantom Armor [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 5-7 | — |
| Phantom Emblem [Base] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Phantom Emblem [Blossom] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Phantom Gloves [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 5-7 | — |
| Phantom Gloves [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 5-7 | — |
| Phantom Vest [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 5-7 | — |
| Phantom Vest [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 5-7 | — |
| Pilfer | Augment | Orb | Varies | Stage 3 | Immediate: 0 orbs. Delayed: 1 champion orb per qualifying round, plus 1 Thief's Gloves orb at the threshold. |
| Portable Forge | Augment | Non-Orb | 0 | Stage 2/Stage 3/Stage 4 | — |
| Potioncraft [Base] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Potioncraft [Blossom] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Potted Lifebloom [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Potted Lifebloom [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Potted Stonebark [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Potted Stonebark [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-7 | — |
| Primal Phoenix blessing | Trait | Orb | 4 | Trait mechanic | Immediate: 0 orbs. Delayed: 1 component orb at each of 4 thresholds. |
| Promised Protection | Augment | Orb | 1 | Stage 2/Stage 3 | — |
| Propagate [Base] | Wisp | Conditional | 0–1 | Stage 2-1 to 4-1 | Copied champion becomes an orb only if the unit bench is full. |
| Propagate [Blossom] | Wisp | Conditional | 0–1 | Stage 2-1 to 4-1 | Copied champion becomes an orb only if the unit bench is full. |
| Radiant Rascal | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Radiant Relics | Augment | Mixed | 1 | Stage 2/Stage 3/Stage 4 | 1 Remover orb; Radiant item is chosen from an armory. |
| Recombobulator | Augment | Orb | 2 | Stage 3 | — |
| Replication | Augment | Conditional | 0–2 | Stage 2/Stage 3 | Each copied component becomes an orb only if the item bench is full. |
| Retribution | Augment | Orb | 2 | Stage 3/Stage 4 | — |
| Salvage Bin | Augment | Orb | 2 | Stage 2 | Immediate: 1 completed item orb. Delayed: 1 component orb after 8 player combats. |
| Salvage Bin+ | Augment | Orb | 2 | Stage 3/Stage 4 | Immediate: 1 completed item orb. Delayed: 1 component orb after 4 player combats. |
| Salvager [Base] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Salvager [Blossom] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Scrappy [Base] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Scrappy [Blossom] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Seraphim's Staff | Augment | Orb | 1 | Stage 2/Stage 3 | — |
| Shimmerscale Essence | Augment | Orb | 2 | Stage 2 | Immediate: 1 Mogul's Mail orb. Delayed: 1 Gambler's Blade orb after 7 player combats. |
| Slice of Life | Augment | Non-Orb | 0 | Stage 2 | — |
| Slightly Magic Roll | Augment | Orb | 0–1 | Stage 2 | Rerolls/Hugeify: 0; other outcomes: 1 bundled orb. |
| Small Furry Friend | Augment | Non-Orb | 0 | Stage 2/Stage 3/Stage 4 | — |
| Small Grab Bag | Augment | Orb | 2 | Stage 3/Stage 4 | — |
| Smurfing [Base] | Wisp | Orb | 1 | Stage 3-5 to 4-1 | — |
| Smurfing [Blossom] | Wisp | Orb | 1 | Stage 3-5 to 4-1 | — |
| Solar Gift [Base] | Wisp | Orb | 3 | Stage 2-1 to 3-4 | — |
| Solar Gift [Blossom] | Wisp | Orb | 3 | Stage 2-1 to 3-4 | — |
| Solo Leveling | Augment | Orb | 2 | Stage 2 | Immediate: 0. Delayed: 2 component orbs after 5 combats. |
| Solo Plate | Augment | Orb | 1 | Stage 2/Stage 3 | — |
| Speedy Double Kill | Augment | Orb | 1 | Stage 2 | — |
| Spirit Of Redemption | Augment | Orb | 1 | Stage 2/Stage 3 | — |
| Spreading Roots | Augment | Orb | 1 | Stage 2 | — |
| Spreading Roots+ | Augment | Orb | 1 | Stage 3 | — |
| Staffsmith | Augment | Orb | 2 | Stage 4 | — |
| Sun and Moon | Augment | Non-Orb | 0 | Stage 3 | — |
| Sun and Moon+ | Augment | Non-Orb | 0 | Stage 4 | — |
| Sweet Treats | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Sword Overflow | Augment | Orb | 4 | Stage 3/Stage 4 | — |
| Swordsmith | Augment | Orb | 2 | Stage 4 | — |
| Tactician's Kitchen | Augment | Orb | 2 | Stage 2 | Immediate: 1 Emblem orb. Delayed: 1 Tactician's Cape after 3 rounds. |
| Team Building | Augment | Orb | 2 | Stage 2/Stage 3 | Immediate: 1 Lesser Duplicator orb. Delayed: 1 orb after 5 player combats. |
| Teemo mushrooms | Champion | Non-Orb | 0 | Champion mechanic | Collectible, but all three mushrooms carry BonusGift.IgnoreLoot. |
| The Golden Dragon | Augment | Orb | 1 | Stage 3 | — |
| The Golden Egg | Augment | Mixed | 1–2 | Stage 4 | Immediate: Egg becomes an orb only if the unit bench is full. Delayed: 1 bundled orb when the egg hatches. |
| The Tower | Augment | Non-Orb | 0 | Stage 2/Stage 3/Stage 4 | — |
| The Trait Tree | Augment | Orb | 1 | Stage 2 | — |
| The Trait Tree+ | Augment | Orb | 1 | Stage 3 | — |
| Thingamajig Bag [Base] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-1 | — |
| Thingamajig Bag [Blossom] | Wisp | Non-Orb | 0 | Stage 3-1 to 4-1 | — |
| Thingamajig Jar [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Thingamajig Jar [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | — |
| Thingamajig Sack [Base] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Thingamajig Sack [Blossom] | Wisp | Non-Orb | 0 | Stage 5-1 to 10-1 | — |
| Three Me [Base] | Wisp | Orb | 1 | Stage 3-1 to 4-1 | — |
| Three Me [Blossom] | Wisp | Orb | 1 | Stage 3-1 to 4-1 | — |
| Training Yard [Base] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Training Yard [Blossom] | Wisp | Non-Orb | 0 | Stage 4-2 to 5-7 | — |
| Trait Ladder | Augment | Orb | Varies | Stage 2 | Immediate: 0. Delayed: 1 per breakpoint; later breakpoints repeat the level-14 reward. |
| Truce [Base] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | Loose gold coins; not eligible. |
| Truce [Prismatic] | Wisp | Non-Orb | 0 | Stage 2-1 to 10-1 | Loose gold coins; not eligible. |
| Truce [Blossom] | Wisp | Non-Orb | 0 | Stage 2-1 to 2-7 | Loose gold coins; not eligible. |
| U.R.F | Augment | Orb | 1 | Stage 2/Stage 3/Stage 4 | — |
| Unrivaled | Augment | Non-Orb | 0 | Stage 2/Stage 3 | — |
| Urf's Grab Bag | Augment | Orb | 1 | Stage 3/Stage 4 | — |
| Wand Overflow | Augment | Orb | 4 | Stage 3/Stage 4 | — |
| Warpath | Augment | Mixed | 1 | Stage 2 | Immediate: 0 orbs; champion goes to the unit bench. Delayed: 1 bundled cashout orb. |
| We Stick Together | Augment | Orb | 2 | Stage 2 | — |
| Weight The Worth | Augment | Mixed | 2+ | Stage 3 | Immediate: 2 Duplicator orbs. Delayed: Champion copies become an orb only if the unit bench is full. |
| Worth the Wait | Augment | Non-Orb | 0 | Stage 2 | — |
| Worth the Wait II | Augment | Non-Orb | 0 | Stage 2 | — |
| Woven Magic | Augment | Orb | 4 | Stage 2 | Immediate: 1 component orb. Delayed: up to 3 completion orbs. |

</details>

### A.2 System tables

Index: [LBB system tables](https://www.littlebuddybot.com/tft-system-tables).

| Page or graphic | Result | Remaining limitation |
| --- | --- | --- |
| Shop odds / pools / XP | Recovered, §1.1–1.3 | XP source disagreement |
| Encounters | All 20 LBB rows recovered, §2.1 | Displayed sums 103% / 88%; exact probabilities unresolved |
| Augment odds | Published sequences and conditional branches recovered, §1.5 | Rounded/inconsistent totals; encounter-conditioned exact distributions |
| Loot orbs | Gray/Silver, Blue, Gold, Prismatic recovered, §3 | No inferred sub-outcome weights |
| Player damage | Recovered, §1.6 | Exceptions not described by graphic |
| Gold Subscription | Five published payout rows recovered, §2.2 | Selection coupling and Stage-8+ behavior |
| Reroll Subscription | Stages 2–7 recovered, §2.3 | Expiry/carryover and later stages |

### A.3 Trait tables

Index: [LBB trait tables](https://www.littlebuddybot.com/tft-trait-tables).

| Graphic / topic | Result | Remaining limitation |
| --- | --- | --- |
| Coven | All nine published thresholds and 35 outcome rows recovered, §4 | Source revisions/generation differ; rounded chances |
| Blackthorn | Cost × role × star × trait-count matrix recovered, §5.3 | Source multiplier conflict and unusual cell; four-star sacrifices |
| Riftbeast | Level 4–10 shop marginals and copy caps recovered, §6.3 | Full lineup weights and three-star-owned behavior |
| Fae | Normal thresholds, Embiggen values, seven Golden payouts recovered, §7.2 | Counter/reset/carryover rules |
| Primal | Four exact published blessing effects recovered, §9.7 | Breakpoint mapping and stacking interpretation |
| Lux / Avatar | Graphic read and compared, §8 | Three numerical source conflicts |
| Sprykin | BFF/SFF rider and ability values recovered, §9.1 | Base stat sheet; sharing/recipient conflict |
| Prismatic traits | 11 Blossom / Elderwood quests recovered, §9.2–9.3 | Three Prismatic Wisp effects remain qualitative |
| Elderwood / Ornn | Known quest behavior retained, §9.3 | Forge Power thresholds not found |

### A.4 Augment tables

Index: [LBB augment tables](https://www.littlebuddybot.com/tft-augment-tables).

| Table | Result | Remaining limitation |
| --- | --- | --- |
| Call to Chaos | Rechecked, §10.1 | Rounded odds |
| Golden Egg | Rechecked, §10.2 | One source-conflicting reward bundle |
| Expedition | Cashout corroborated, §10.3 | No explicit numerical probability field |
| Trait Ladder | All 13 rungs recovered, §10.7 | Source conflicts; unspecified rung-11 item-type odds |
| Loaded Dice | All listed interactions recovered, §10.8 | Exact conditional dice distribution / unlisted interactions |
| Blossom’s Call | Stage 4–6 outcome matrix recovered, §10.9 | Stage 7+ and selection weights |
| Booster Pack | All 33 graphic rows recovered, §10.10 | Star/package differences and + chance total |
| Frontline / Backline | All ten champion/emblem pairings recovered, §10.11 | No pairing weights |
| Warpath | Cashout recovered, §10.12 | No explicit probability field |
| Slightly Magic Roll | Faces 1–6 recovered, §10.13 | Face probabilities not supplied |
| A Magic Roll | Outcomes and special egg recovered, §10.14 | Source discrepancies; low-triple gold mapping |
| Expected Unexpectedness | All 15 stage outcomes recovered, §10.15 | Exact roll-to-row mapping not shown |
| Missed Connections | Both layouts checked, §10.16 | Layout change/overlap interpretation; exact coordinates |
| Slice of Life | Complete published schedule recovered, §10.16 | No champion selection weights |
| Hard Commit | Delivery rule and named pools recovered, §10.17 | Champion selection weights |
| Solo Leveling | Exact listed stat bonuses recovered, §10.18 | No separate scaling table supplied |
| Bonus Gift | Full classification ledger recovered, §10.19 / A.1.3 | Missing/unlisted sources not assumed eligible |

### A.5 Wisp tables

Index: [LBB Wisp tables](https://www.littlebuddybot.com/tft-wisp-tables).

| Graphic / database | Result | Remaining limitation |
| --- | --- | --- |
| Heroic Sacrifice | Base/Blossom stats and offer prerequisites recovered, §11.3–11.4 | No inferred strongest-unit tie-breaker |
| Hand of Baron | Base/Blossom stats and prerequisite recovered, §11.3–11.4 | No extra variant scaling inferred |
| Preppers | All 12 item rows recovered, §11.5 | Stack-to-stat conversions not inferred |
| Potions / Potioncraft | All six item effects, quantities and windows recovered, §11.6 | Expiry/retrigger details |
| Prismatic Wisps | All 19 exposed entries reviewed, §11.7 | Blaze, Giant’s Aura, Treetop Archers numeric effects |
| Full offer catalog | All 366 published records included, A.1.1 | Selection weights; cooldown reset exceptions |

### A.6 Other information

Index: [LBB other information](https://www.littlebuddybot.com/tft-other-info).

The 20-emblem recipe/effect chart is recovered in §12.1. The September 16 solo-Stage-1 chart is recovered in §12.2, with its unstated test assumptions preserved as a limitation. Older-set effect-source graphics were excluded. The selected item lookup retains the scope of the original document.

## Appendix B. Coverage boundaries

This file is a mechanical reference organized around the uploaded document’s sections and gap checklist. It adds the recovered tables and complete factual offer/classification ledgers, but does not claim an exhaustive champion stat database, item-effect catalog, copied tooltip collection, or match-derived meta ranking.

The remaining material should be added as actual supported tables and rules when available—not guessed values or statements that reward contents prove the strategically best play. Reward contents, eligibility, selection probabilities, and observed performance remain distinct. Source-specific conflicts and genuinely unresolved mechanics are listed in §13 and beside the affected entries.
