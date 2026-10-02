# UN4-1 — Unit investment, carry versions and alternative holders

Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.

## UN4-1-C01 — Veigar carry investment versus trait support

### Question

What separates a Veigar reroll carry board from a board that just uses him for traits? How much do his items and the rest of the team change whether three-star Veigar is worth building around?

### Concrete analytical scenario

Veigar2/3 crossed with zero, partial and three completed items; four-star versions kept separate. 'Carry' and 'support' are declared investment proxies, not measured damage roles.

### Reference requirements translated to ChatTFT

Use query_cohort for Veigar board families, grouping unit_name with unit_star_level and unit_item_count, selecting Veigar rows explicitly. Discover recurring partners with cohort unit/trait deltas and verify joint core predicates. compare_cohorts compares item-count/star cells within shared named support and final-level conditions; rank_unit_loadouts distinguishes actual ordinary/special trios.

### Metrics and acceptance checks

Report role-cell counts/shares and mean/top4/win without combining independent item and star marginals. Keep partial and four-star groups visible. Explain which supported companions and item packages accompany stronger finishes; do not equate Veigar3 average with payoff from rolling for him.

### Capability limits and preparation

No attempted-reroll denominator, stacking history, automatic whole-board matching or generic carry-role field. Cell shares use a declared board family and cannot be reconstructed from suppressed rows.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [UN4-1-C01 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/units/lanes/un4-1/cases.md) · original status provisional/incomplete. Proposal lineage: UN4-1-R2-P1.

## UN4-1-C02 — Exact special trio on Yi2 versus Draven1

### Question

With Flickerblade, radiant Quicksilver and Edge of Night, is two-star Master Yi or one-star Draven the better carry? How much does the rest of the board change that?

### Concrete analytical scenario

Master Yi2 versus Draven1, exactly Flickerblades, radiant Quicksilver and ordinary Edge of Night on the candidate. Supporting boards are discovered, not preset.

### Reference requirements translated to ChatTFT

Resolve named holders and exact special variants, then rank_unit_loadouts for legal recorded trios and compare_cohorts for the two one-copy holder/star/trio groups. Separate both-holder boards; discover support with query_cohort/deltas and repeat in shared supported contexts.

### Metrics and acceptance checks

Preserve Yi2/Draven1 asymmetry and radiant identity. Show both exact samples, outcomes and conditional board dependence. Yi3 and Draven2 are explicitly separate sensitivities. Do not infer Yi form from identity route, build label or a vague offensive-item category.

### Capability limits and preparation

Local context is older than 18.3B and cannot settle disputed effect values. Presence of a recorded exact trio establishes an observed build, not complete current item legality or acquisition opportunity.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [UN4-1-C02 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/units/lanes/un4-1/cases.md) · original status provisional/incomplete. Proposal lineage: UN4-1-R2-P2.

## UN4-1-C03 — Is special-item Veigar a different ceiling?

### Question

Does three-star Veigar with normal items still have a strong endgame, or do Dawncore and Flora Fatalis versions account for most of his top finishes?

### Concrete analytical scenario

Veigar3 with three items; distinguish ordinary-only holder builds, Dawncore builds, and Flora Fatalis-active support, including their overlap.

### Reference requirements translated to ChatTFT

Discover exact loadouts and resolve Flora Fatalis as a trait, not an item. Define ordinary on Veigar from named trio identities; compare Dawncore/ordinary holder packages within shared cores and recorded Flora Fatalis activation. Query named Fiddlesticks/Soraka support and frontline loadouts. Global ordinary-only boards require separate certification.

### Metrics and acceptance checks

Report placement distribution/top4/win with sample sizes and the contribution of each disjoint declared group to observed top finishes where histograms allow it. Higher special-group win rate alone does not prove most wins came from that group. Preserve Dawncore+Flora overlap.

### Capability limits and preparation

Flora Fatalis is not an ordinary-versus-artifact item category. No generic board-wide artifact exclusion or survival-to-reroll denominator; no numerical ceiling or winner is fixed in advance.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [UN4-1-C03 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/units/lanes/un4-1/cases.md) · original status provisional/incomplete. Proposal lineage: UN4-1-R2-P1.

## UN4-1-C04 — Who receives the tank investment beside Veigar?

### Question

On finished three-star Veigar boards, how do Ornn-focused, Alistar-focused and split frontline investment compare?

### Concrete analytical scenario

Veigar3 end states with Ornn and Alistar considered as frontline investments. Start with explicit item-count allocations, such as 3/0, 0/3 and 1/2 or 2/1 across the two holders, and exact-star strata.

### Reference requirements translated to ChatTFT

Inspect both tanks' star/item-count/loadout rows, then declare supported allocation cells rather than assuming an arbitrary 3/3 split is comparable to 3/0. compare_cohorts uses shared Veigar/core/level and named tank star/item constraints; query_cohort reports total-item distribution. Preserve absent-tank and both-three-star groups explicitly.

### Metrics and acceptance checks

Define focused/split quantitatively in input or visible analytical assumptions. Report each joint cell's counts, mean/top4/win and exact tank build context. Compare equal named-holder item budgets where possible and separate richer 3/3 boards.

### Capability limits and preparation

Equal allocation across these two tanks does not match the rest of the board. Item count is not a defensive-item taxonomy; named tank loadouts must justify the role label. No tank survival or artifact-production timeline.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [UN4-1-C04 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/units/lanes/un4-1/cases.md) · original status provisional/incomplete. Proposal lineage: UN4-1-R2-P1.
