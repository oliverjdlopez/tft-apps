# IT-3 — How item performance varies with board and trait context

Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.

## IT-3-C01 — Gunblade behind Juggernauts

### Question

Does Gunblade become a better item on Zyra when she's playing behind Juggernauts, or do those boards just do well regardless of her build?

### Concrete analytical scenario

Zyra2 with three ordinary completed items. Compare Gunblade versus supported alternative thirds sharing the other pair, separately in lower, four and six Juggernaut contexts.

### Reference requirements translated to ChatTFT

Discover Zyra loadouts, then use holder-bound compare_cohorts within each verified Juggernaut contribution interval. Condition named Maokai presence, Summoner activation and tank/carry investment where support permits. Inspect count/level distributions with query_cohort.

### Metrics and acceptance checks

Evaluate the item contrast within each context before discussing whether it differs across contexts; report cell sizes and mean/top4/win. A strong Gunblade+Juggernaut marginal alone cannot establish the interaction. Difference-of-differences is a descriptive derived comparison; no native interaction significance test exists.

### Capability limits and preparation

No generic all-healing-source control, combat healing or universal matched-board budget. Trait medal alone cannot encode four versus six.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-3-C01 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-3/cases.md) · original status provisional/incomplete. Proposal lineage: IT-3-R2-P1.

## IT-3-C02 — Elise carry pair without the emblem

### Question

Is Rageblade–Titan's Elise actually good in ordinary Vanguard boards, or does it only look good when she has a Ravager emblem?

### Concrete analytical scenario

Elise3 with three items, split four/six Vanguard. Ordinary Rageblade/Titan's plus an ordinary third is distinct from Rageblade/Titan's/Ravager Emblem with active Ravager. Elise2 is a separate sensitivity.

### Reference requirements translated to ChatTFT

Discover exact Elise loadouts and compare ordinary carry alternatives inside Vanguard strata, then inspect the emblem-bearing complete package with the emblem explicitly bound to Elise and Ravager active. Keep the one-holder guard and exact third item visible; do not silently replace Titan's with an emblem.

### Metrics and acceptance checks

Report within-context build outcomes, counts and the ordinary versus emblem package difference, with the lost ordinary third slot stated. Judge whether ordinary builds have supported outcomes rather than requiring the emblem hypothesis to win.

### Capability limits and preparation

Ordinary-only on Elise can be established by exact triplet identity; global no-special-items cannot be assumed. Coven rewards, acquisition and damage role are not observed.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-3-C02 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-3/cases.md) · original status disputed/incomplete. Proposal lineage: IT-3-R2-P2.

## IT-3-C03 — Red Buff inside Inferno

### Question

Does Red Buff still improve Ashe's endgame results when the board already has Inferno, or is its good average mostly coming from boards without that trait?

### Concrete analytical scenario

Fully itemized Ashe at one and two stars separately; Red Buff versus an observed alternative third sharing the other pair, within active Inferno strata and genuinely without-active-Inferno boards.

### Reference requirements translated to ChatTFT

Use rank_unit_loadouts to discover comparable trios. For each build, compare active Inferno to its complement within the Ashe build shell to include boards with no Inferno row. Use explicit build comparisons in active contribution strata and report differences; do not implement missing-trait absence with active:false alone. Track Inferno Emblem on Ashe separately.

### Metrics and acceptance checks

Cross build and trait context instead of using Red Buff's pooled average. Report star-specific cell support, mean/top4/win and available uncertainty. Distinguish native allied trait activation, emblem consumption of a slot, and other named burn equipment.

### Capability limits and preparation

A complement supplies a valid inactive-or-absent summary but cannot be reused as a general nested filter; fully crossed no-Inferno build contrasts may need separate complements with descriptive comparison. No opponent burn coverage or exact combat overlap is measurable.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-3-C03 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-3/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## IT-3-C04 — Morgana utility and the second carry

### Question

Is Morello–Void Staff Morgana a good build on her own, or do its results depend on having a fully itemized Ahri beside her?

### Concrete analytical scenario

Morgana2 with three ordinary items: Morello/Void Staff plus an explicit third versus observed damage trios, crossing Ahri2 with three items, Ahri underitemized, another named AP carry, and no such itemized carry.

### Reference requirements translated to ChatTFT

Discover exact loadouts and candidate partners. Compare holder builds with compare_cohorts inside named Invoker/frontline shells. Define partner investment with UnitCondition item counts/stars; exclude a bounded named AP-carry candidate set only if complete for the declared pool. Query total equipment and other holder loadouts descriptively.

### Metrics and acceptance checks

Separate Morgana's own build association from the partner association and give cell counts/outcomes. Define 'on her own' as no other declared fully itemized AP carry, not no other units. Statikk is an artifact candidate, not ordinary Void Staff equivalence.

### Capability limits and preparation

No generic AP-role predicate, no global item-budget matching, and no inference of actual damage share. Candidate-pool-limited absence must be labeled.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-3-C04 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-3/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## IT-3-C05 — Mama Beak across board families

### Question

Does Titan's actually beat Kraken on carry Mama Beak in Summoner boards, and does that still hold when she's played in a Riftbeast-heavy board?

### Concrete analytical scenario

Mama Beak3 with three ordinary items first; Titan's versus Kraken with a supported shared pair. Two-star results separate. Summoner and Riftbeast contexts can overlap.

### Reference requirements translated to ChatTFT

Discover loadouts, query each named trait's contribution rows, then explicitly condition both trait intervals to create joint cells. Compare exact holder triplets within those cells and common named carry/frontline conditions. Inspect two-star cells separately.

### Metrics and acceptance checks

Keep hybrids visible; do not pretend Summoner and Riftbeast are exclusive families. Report within-cell build counts and mean/top4/win before discussing variation across families; itemized carry conditions exclude naked trait fillers.

### Capability limits and preparation

Alpha Mark ownership is not exposed and cannot be inferred from the cohort. Joint trait cells need conjunctive filters, not two marginal trait rows.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-3-C05 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-3/cases.md) · original status disputed/incomplete. Proposal lineage: none.

## IT-3-C06 — Seeker’s and trait-provided stats

### Question

Is Seeker's Armguard worse than Crownguard on Fiddlesticks when I play lots of Defenders and Spellweavers, or do the results still favor it there?

### Concrete analytical scenario

Fiddlesticks3 with Adaptive Helm/Titan's, varying Seeker's Armguard versus ordinary Crownguard; repeat two-star separately and cross Defender/Spellweaver support.

### Reference requirements translated to ChatTFT

Resolve artifact versus ordinary identities, discover fixed-pair loadouts and compare exact one-copy holder trios in explicit joint Defender/Spellweaver contribution strata. Preserve Flora Fatalis and Soraka conditions where visible and inspect other special-item holders.

### Metrics and acceptance checks

Report counts and placement/top4/win effects for the fixed pair, including uncertainty. Do not collapse trait contexts or attribute any effect to armor/AP saturation, takedown stacks or duration. A wider pair comparison is a labeled sensitivity only.

### Capability limits and preparation

Artifact acquisition and exact whole-board artifact count are not cohort filters. They remain residual selection differences even with equal holder item counts.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-3-C06 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-3/cases.md) · original status disputed/incomplete. Proposal lineage: none.
