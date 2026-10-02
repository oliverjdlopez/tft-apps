# IT-2 — Fixed-inventory holder comparisons and item allocation

Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.

## IT-2-C01 — One AD inventory across three endgame holders

### Question

With Shojin, Infinity Edge and Last Whisper, how do two-star Ezreal, Sivir and Yunara compare as endgame carries? What trait support makes each worth considering?

### Concrete analytical scenario

Compare two-star Ezreal, Sivir and Yunara carrying the same ordinary Shojin/Infinity Edge/Last Whisper trio, retaining their different trait support packages.

### Reference requirements translated to ChatTFT

Resolve all holders and the trio. Query each exact one-copy holder cohort; use rank_unit_loadouts as build support discovery and compare_cohorts for explicit pairwise comparisons. Within each holder cohort use get_cohort_trait_deltas or query_cohort for observed trait contribution counts, then compare reportable named support strata. Mark boards containing multiple candidate carries or compare mutually exclusive candidate groups separately.

### Metrics and acceptance checks

All three holder/star/trio intersections must be investigated; no Yunara-three-star substitution. Report each sample and mean/top4/win, trait-support prevalence and conditional outcomes. A pooled holder ordering must not imply that all supporting traits and inventories were identical.

### Capability limits and preparation

Board size and total item budget are groupable diagnostics, not direct cohort filters; exact defensive-item roles need a declared named-item classification. No holder winner is preset.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-2-C01 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-2/cases.md) · original status provisional/incomplete. Proposal lineage: IT-2-R2-P1.

## IT-2-C02 — One Helm across carry and tank

### Question

On an Azir–Malphite board, is Adaptive Helm better as Azir's third item or Malphite's? I'm comparing three-star Azir with Nashor's Tooth and Jeweled Gauntlet against two-star Malphite with Warmog's and Gargoyle.

### Concrete analytical scenario

Both Azir3 and Malphite2 present. A: Azir Nashor/JG/Helm and Malphite Warmog/Gargoyle. B: Azir Nashor/JG and Malphite Warmog/Gargoyle/Helm. Each arm has five completed items across these two holders.

### Reference requirements translated to ChatTFT

Use compare_cohorts with holder-bound item predicates and exact completed-item counts for both one-copy holders, sharing the unit stars and final-level/core conditions. Use cohort unit/trait discovery to find supported shell strata rather than inventing the unspecified rest of the board.

### Metrics and acceptance checks

Verify both allocations jointly, not separate Azir and Malphite marginals. Preserve the 3/2 versus 2/3 counts and normal variants. Report joint sample sizes, placement distribution, mean/top4/win and uncertainty within supported common shells; distinguish pair inventory equality from whole-board equality.

### Capability limits and preparation

No fixed whole-board inventory or causal marginal value of Helm is implied. Other holders and total equipped count can be described with query_cohort but cannot all be automatically matched.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-2-C02 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-2/cases.md) · original status provisional/incomplete. Proposal lineage: IT-2-R2-P2.

## IT-2-C03 — Damage and utility bundles across two carries

### Question

On a final board with two-star Ashe and two-star Sivir, should Ashe get Shojin, Red Buff and Last Whisper while Sivir gets Blue Buff, Infinity Edge and Striker's Flail, or should those two complete builds be reversed?

### Concrete analytical scenario

Both Ashe2 and Sivir2, each with three items. Compare Ashe Shojin/Red Buff/Last Whisper plus Sivir Blue Buff/Infinity Edge/Striker's Flail against the full reversed allocation.

### Reference requirements translated to ChatTFT

Resolve holders/items and compare two explicit six-item allocations using one-copy holder guards, exact stars and per-holder item counts. Discover support with query_cohort or delta tools; re-query meaningful Hunter/Juggernaut strata through trait contribution conditions rather than comp labels.

### Metrics and acceptance checks

Six items and both complete bundles must be retained in each joint arm. Report sample/mean/top4/win and histogram/intervals where available. A successful individual Ashe trio is not evidence for the joint assignment. Describe whether trait context changes the observed comparison.

### Capability limits and preparation

Other utility holders are observable only as final items; burn/shred uptime and transfer timing are not. Total board-item equality remains a grouped diagnostic.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [IT-2-C03 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/items/lanes/it-2/cases.md) · original status provisional/incomplete. Proposal lineage: none.
