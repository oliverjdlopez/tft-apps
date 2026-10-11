# CO4-2 — Recurring final-board cores and flexible slots

Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.

## CO4-2-C01 — Five-cost soup families

### Question

People keep calling the level-nine boards “five-cost soup,” but they don't all look alike. What recurring cores show up in those endgame boards, and which units are actually flexible around them?

### Concrete analytical scenario

Level-nine 'five-cost soup' as a declared candidate family. Start with observed cost-five partner frequency, then explicitly investigate repeated named pairs/cores without excluding low-cost anchors by definition.

### Reference requirements translated to ChatTFT

query_cohort at final level nine grouped by unit_name/unit_cost discovers relevant candidates. There is no board-level at-least-N-five-cost predicate: enumerate named candidate-pair cohorts and use unit deltas/grouping within them, then test complete support conjunctions. Compare core prevalence before optional outcomes; keep overlapping families explicit.

### Metrics and acceptance checks

Return supported recurring cores and flex alternatives with counts and denominators, not a list of high marginal win-rate units. Verify at least one joint recurrence claim per named core; distinguish absent core members and candidate coverage. Vary the declared soup inclusion proxy transparently.

### Capability limits and preparation

No automatic full-roster clustering, arbitrary pair grouping or exact global legendary-count rule. This is bounded anchored discovery; exhaustive family partitions require prepared composition aggregates beyond the public tools.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [CO4-2-C01 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/compositions/lanes/co4-2/cases.md) · original status provisional/incomplete. Proposal lineage: CO4-2-R2-P1.

## CO4-2-C02 — Elderwood Veigar core and flex

### Question

When I look up Elderwood Veigar, the finished boards aren't all the same. Which units keep showing up together, and what are the main ways people fill the remaining slots?

### Concrete analytical scenario

Veigar3 with recorded active Elderwood, without requiring a guide roster in the initial family. Discover core and flex from all-placement boards.

### Reference requirements translated to ChatTFT

Use unit/trait deltas and query_cohort for partner stars/loadouts and level/board-size distributions. Test candidate core conjunctions by adding named unit conditions, then compare with/without alleged members in the broader family. Keep the family independent of Ornn until his recurrence is measured.

### Metrics and acceptance checks

Show measured joint support and member absence, not only independent high-frequency rows. Separate final-level/tank-star/build contexts and distinguish ordinary holder builds from full-board categories. Outcomes describe observed cores, not compulsory guide templates.

### Capability limits and preparation

No complete-roster signature or flex-slot identity is returned; a contains-core query includes additional units. Topological clustering and boardwide special exclusions remain preparation gaps.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [CO4-2-C02 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/compositions/lanes/co4-2/cases.md) · original status provisional/incomplete. Proposal lineage: CO4-2-R2-P2.

## CO4-2-C03 — AD pairs beyond fixed templates

### Question

In finished AD boards, are Aphelios–Brambleback and Sivir–Nidalee really two fixed pairs, or do the carries recombine into other recurring boards? Which support units stay together when they do?

### Concrete analytical scenario

Investigate all six named pairs among Aphelios, Brambleback, Sivir and Nidalee, including cross-pairs and higher-order overlaps, with itemized-carry versus filler proxies.

### Reference requirements translated to ChatTFT

The DSL has no at-least-two-of-four OR condition. Run bounded conjunctive queries for each pair and selected triple/quad intersections; define mutually exclusive pair-only cells through explicit absence where needed. Within cells discover support frequencies and verify proposed joint support packages.

### Metrics and acceptance checks

Cover all six pairs rather than just the two named templates. Report overlapping cells without summing them into unique family totals; identify actual itemized roles, recurring shared support and inspected-page coverage. No causal pair ordering required.

### Capability limits and preparation

Cannot get a union denominator or full family partition by blindly summing pair rows. Generic AD/form labels require explicit item-based proxies; joint roster discovery remains bounded.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [CO4-2-C03 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/compositions/lanes/co4-2/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## CO4-2-C04 — AP frontline packages

### Question

For finished Zyra/Soraka boards, what does the rest of the team look like when Malphite and Sentinel aren't the frontline? Are there recurring alternatives, or just scattered emergency boards?

### Concrete analytical scenario

Separate itemized Zyra-only, Soraka-only and both-carry families; investigate final boards lacking both Malphite and Sentinel before separately labeling single-anchor-absent variants.

### Reference requirements translated to ChatTFT

Use explicit named absence predicates and carry investment to construct disjoint families. Discover replacement frontliners and companion loadouts with query_cohort/deltas, then verify recurrent joint packages. Query level/board_size/item-budget distributions and compare named support packages where support is adequate.

### Metrics and acceptance checks

State whether 'without the frontline' means neither anchor or a partial replacement. Show recurrence counts and concrete multi-unit alternatives, not isolated tank ranks. Preserve inclusive Zyra/Soraka interpretation and itemized versus naked carry proxies.

### Capability limits and preparation

'Emergency board' is player intent/history and cannot be inferred. Complete package coverage and exact deployed-slot matching need richer prepared evidence.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [CO4-2-C04 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/compositions/lanes/co4-2/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## CO4-2-C05 — Teemo presence versus Teemo composition

### Question

When Teemo shows up in several top-four endgame boards, are those actually the same composition? What recurring cores separate Teemo carry boards from boards that just keep him alongside another carry?

### Concrete analytical scenario

Teemo-containing top-four final boards, distinguishing Teemo itemized-carry and low-item companion proxies; retain all-placement sensitivity separately.

### Reference requirements translated to ChatTFT

No placement filter exists in FilterGroup. Use query_cohort with placement among at most three dimensions, selecting returned placements 1–4 for reportable role/partner groups. Sum only disjoint returned placement cells for the same group when complete; otherwise mark top-four support incomplete. Discover candidate cores on all placements, then verify each candidate's top-four counts through reportable compare_cohorts histograms without selecting on outcome inside the DSL.

### Metrics and acceptance checks

Do not silently replace the requested top-four population with all boards. Report top-four-specific recurrence/role denominators only when complete and distinguish them from outcome success rates. Same Teemo presence is not evidence of the same comp; verify joint core membership.

### Capability limits and preparation

Suppressed placement cells prevent exact sums and may require a prepared top-four population. No complete-roster grouping, generic primary-carry role or automatic exhaustive comp partition.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [CO4-2-C05 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/compositions/lanes/co4-2/cases.md) · original status provisional/incomplete. Proposal lineage: none.

## CO4-2-C06 — Two meanings of Murkwolf boards

### Question

Are the finished boards people call Warwick–Murkwolf reroll actually the same family as vertical Riftbeast boards that carry Murkwolf? Which units define each core, and where do they overlap?

### Concrete analytical scenario

Itemized Murkwolf end states: Murkwolf3+Warwick3, high recorded Riftbeast contribution strata, and the hybrid intersection.

### Reference requirements translated to ChatTFT

Create explicit star/item-count anchor cohorts, query their unit/trait support, and verify repeated named cores. compare_cohorts or grouped queries measure overlap and package outcomes; cross Riftbeast contribution intervals rather than treating a guide label as a condition.

### Metrics and acceptance checks

Report each core's recurrence, shares with declared denominators and hybrid overlap. Preserve Murkwolf stars/items and Warwick investment, with level/unit-count differences visible. A prediction or marginal Murkwolf average is not a family map.

### Capability limits and preparation

Contains-core queries cannot identify every flex slot or certify a full-roster partition. Alpha Mark, sacrifices and combat behavior are unavailable.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [CO4-2-C06 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/compositions/lanes/co4-2/cases.md) · original status provisional/incomplete. Proposal lineage: none.
