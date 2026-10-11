# IT-4 — Special-item comparisons across carry and frontline roles

Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.

## IT-4-C01 — Four artifacts across two carries

### Question

For Kayle–Aphelios boards, how do Wit's End, Shiv, Collector and Infinity Force compare between the two carries when the frontline already has its items?

### Concrete analytical scenario

Kayle2 with Rageblade/JG and Aphelios2 with Last Whisper/Red Buff. Compare Wit's End, Statikk Shiv, Gold Collector and Infinity Force on each carry: eight allocation cells, with the other carry retaining two items and a declared three-item tank.

### Reference requirements translated to ChatTFT

Resolve aliases and artifact families; construct eight joint holder allocations with exact 3/2 or 2/3 counts and unique-holder guards. Discover a reportable named frontline shell and compare cohorts within it. Use query_cohort for tank loadouts and whole-board item-count distributions.

### Metrics and acceptance checks

Cover all eight cells or identify the exact unsupported cells without treating blank rows as zeros. Keep carry stars, co-items and artifact variants fixed. Report mean/top4/win, counts and uncertainty with pairwise conclusions limited to supported common shells.

### Capability limits and preparation

'Frontline already has items' must be operationalized as an explicit named tank/loadout in input or discovered and declared. No whole-board equal-special-count predicate; no preset best artifact/holder.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-4-C01 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-4/cases.md) · original status provisional/incomplete. Proposal lineage: IT-4-R2-P1.

## IT-4-C02 — Radiant scaling or radiant protection

### Question

For Zyra–Malphite boards, is radiant Archangel on Zyra worth more than radiant Bramble or Dragon's Claw on Malphite? I'm thinking of Zyra with Shojin and JG and Malphite with just Warmog's.

### Concrete analytical scenario

Zyra2 Shojin/JG and Malphite2 Warmog. Compare radiant Archangel on Zyra (3/1 items) against radiant Bramble or radiant Dragon's Claw on Malphite (2/2 items).

### Reference requirements translated to ChatTFT

Resolve exact radiant variants and build three joint allocations through compare_cohorts, preserving four items across the two unique holders. Inspect other item holders and named support packages through query_cohort before repeating comparisons in shared supported strata.

### Metrics and acceptance checks

Do not normalize away the deliberate 3/1 versus 2/2 asymmetry. Report all three cells' support and placement/top4/win tradeoffs. State separately whether additional radiants elsewhere were actually ruled out.

### Capability limits and preparation

Exactly one radiant anywhere and total-board item equality are not directly enforceable. The live benchmark is an explicitly narrowed holder-allocation comparison unless a prepared population certifies those global restrictions. Blackthorn sacrifice is unobserved.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-4-C02 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-4/cases.md) · original status provisional/incomplete. Proposal lineage: IT-4-R2-P2.

## IT-4-C03 — Concentrate a second artifact or strengthen the tank

### Question

On finished Elderwood Veigar boards that already have Dawncore on Veigar, does a second artifact do more for the board as Luden's on Veigar or as Lightshield Crest on Alistar?

### Concrete analytical scenario

Veigar3/Alistar3 in the same Elderwood stratum. Concentrated: Veigar Dawncore/JG/Luden's, Alistar Warmog/Gargoyle/Spirit Visage. Split: Veigar Dawncore/JG/Blue Buff, Alistar Warmog/Gargoyle/Lightshield Crest.

### Reference requirements translated to ChatTFT

Compare these exact six-item joint allocations with one-copy holder guards and shared core/level/trait contribution conditions. Discover support distributions rather than treating the Elderwood label as a complete roster.

### Metrics and acceptance checks

Two artifacts and six completed items across the two named holders in both arms; verify both replacements. Report counts/histograms/mean/top4/win and effect intervals. This is a whole allocation-package contrast, not the isolated effect of Luden's or Lightshield.

### Capability limits and preparation

Global special count, Veigar permanent AP and Ornn generation history are not fixed by those predicates. No historical marginal is the expected winner.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-4-C03 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-4/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## IT-4-C04 — Radiant Rageblade's apparent Caitlyn advantage

### Question

For completed three-star Caitlyn boards, how much better is radiant Rageblade than Flickerblades or ordinary Rageblade once the frontline and the rest of her build are comparable?

### Concrete analytical scenario

Caitlyn3 with ordinary Kraken/Gunblade plus radiant Rageblade, Flickerblades or ordinary Rageblade, comparing supported common frontline packages.

### Reference requirements translated to ChatTFT

Resolve the three distinct item variants; rank_unit_loadouts establishes exact pair/trio support. compare_cohorts contrasts each alternative within named tank stars/loadouts, core and level; query_cohort describes remaining item investment.

### Metrics and acceptance checks

Report all three exact-build samples and mean/top4/win, emphasizing whether any apparent first-place advantage persists in inspected tank strata. Use uncertainty instead of declaring small differences decisive or an interval crossing zero proof of equivalence.

### Capability limits and preparation

Global radiant/artifact inventory and economic access cannot be matched directly. No live Expedition choice, acquisition probability or fixed numerical improvement is asserted.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-4-C04 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-4/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## IT-4-C05 — An offensive artifact on Ravager Sett

### Question

Do six-Brawler boards with Ravager Sett actually perform better with Hellfire Hatchet or Void Gauntlet on him than with a normal defensive item?

### Concrete analytical scenario

Sett2 holding Ravager Emblem and Warmog, with Hellfire Hatchet, Void Gauntlet or ordinary Gargoyle third, in the six-Brawler activation stratum.

### Reference requirements translated to ChatTFT

Resolve all identities and verify the six-Brawler interval from compatible reference plus recorded contributions. Compare exact one-copy Sett trios inside discovered named carry stars/loadouts. Inspect other artifacts and completed-item distributions as diagnostics.

### Metrics and acceptance checks

All three third-slot outcomes require joint Sett/emblem/trait conditions. Report counts, mean/top4/win, histograms and intervals where available; do not use a broad Sett or artifact average as the comparison.

### Capability limits and preparation

This restrictive cell may be suppressed; the original question must not be broadened silently. No damage-share, survival-time or attack-frequency gold claim.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-4-C05 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-4/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## IT-4-C06 — Eternal Pact depends on the frontline

### Question

Does Eternal Pact on Veigar hold up against Dawncore when I separate completed boards by their main tank and tank itemization, or is its overall item ranking hiding a frontline dependency?

### Concrete analytical scenario

Veigar3 with JG/ordinary Blue Buff plus Eternal Pact or Dawncore, stratified by actual named main-tank investment packages.

### Reference requirements translated to ChatTFT

Discover Veigar triplets and recurring tank partners with loadout/grouped queries. Declare tank role using named defensive items, stars and item count; compare the two exact Veigar builds within each reportable tank/core/level stratum.

### Metrics and acceptance checks

Compare item effects within tank strata before discussing frontline dependence. Show each cell's count and mean/top4/win; a changed pooled ranking is not an interaction by itself. Call the explanatory variable tank presence/investment, not the verified Pact-linked ally.

### Capability limits and preparation

Actual Pact partner, dynamic health, partner death time and casting are unavailable. Global special-item and budget equality is not enforceable; do not let the proxy masquerade as the hidden linkage.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-4-C06 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-4/cases.md) · original status provisional/incomplete. Proposal lineage: none.
