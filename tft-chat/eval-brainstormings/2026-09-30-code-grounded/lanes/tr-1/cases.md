# TR-1 — Trait performance within composition families

Coordinator reconciliation. Read [the common capability contract](../../docs/capabilities.md) with these cases. No outcome winner or exact stored identifier has been assumed. The original source remains the provenance for motivation and historical observations; its web numbers are not gold for ChatTFT.

## TR-1-C01 — Ahri's Invoker dependence

### Question

Do Ahri endgame boards perform well without Invoker, or are the good results mostly coming from boards where she has an Invoker emblem?

### Concrete analytical scenario

Define itemized Ahri independently of Invoker. Distinguish no active Invoker, active Invoker without an emblem on Ahri, and Invoker Emblem actually held by Ahri; preserve named star/build and level strata.

### Reference requirements translated to ChatTFT

Resolve Ahri, Invoker and its emblem. compare_cohorts active Invoker versus its complement within the Ahri investment shell covers missing trait rows. Query explicit active/no-holder-emblem and holder-emblem cells, and inspect counts/traits/loadouts within recurring named cores. Other-holder emblems are a separate inventory category.

### Metrics and acceptance checks

Report group sizes/shares and mean/top4/win without selecting only 'Invoker Ahri' as the whole family. Preserve the distinction between an emblem on Ahri and native allied activation. Compare common mana/item/support contexts and acknowledge sparse overlap.

### Capability limits and preparation

No nested negative trait condition matches absence of a row; active:false alone omits it. Global no-emblem boards are a stronger claim than no emblem on Ahri. Invoker and emblem effect values need a patch-compatible reference beyond the older local baseline.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [TR-1-C01 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/traits/lanes/tr-1/cases.md) · original status provisional/incomplete. Proposal lineage: TR-1-R2-P1.

## TR-1-C02 — Soraka's fourth Executioner versus Kennen

### Question

Do Soraka boards with four Executioners actually finish better than the three-Executioner versions, or is that mostly because those boards also have Kennen?

### Concrete analytical scenario

Itemized Soraka family, independently selected, with recorded three versus four Executioner contributors crossed with Kennen absent versus present: four cells.

### Reference requirements translated to ChatTFT

Use explicit Executioner contributing-unit bounds, verify active state and relevant breakpoint rules, and add Kennen named presence/absence in each cohort. compare_cohorts compares three versus four inside each Kennen stratum and Kennen association inside each contribution stratum. Query actual displaced/support units and item investment.

### Metrics and acceptance checks

All four cells need counts and outcomes or an explicit lack of support; one frequent Kennen row is insufficient. Report within-stratum mean/top4/win differences and distinguish contribution count from medal tier or a causal source of improvement.

### Capability limits and preparation

No automatic interaction significance test or matching on global budget. Lux/Kha'Zix choice must not be reconstructed from roster arithmetic; use recorded traits and mark ambiguous source quality.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [TR-1-C02 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/traits/lanes/tr-1/cases.md) · original status provisional/incomplete. Proposal lineage: TR-1-R2-P2.

## TR-1-C03 — Did Cassiopeia become less tied to six Defender?

### Question

After the 18.3 buffs to Cassiopeia and her tanks, did her endgame boards get better outside six Defender, or is six Defender still carrying her results?

### Concrete analytical scenario

Cassiopeia as an itemized carry, with two/four/six Defender contribution strata. The historical before/after claim requires separate verified pre-18.3 and post-18.3 data with compatible collection provenance.

### Reference requirements translated to ChatTFT

In the current selected scope, discover exact Cassiopeia builds and compare Defender strata inside named core/star/level conditions. A second independently pinned run can produce the other window's same strata, but compare_cohorts cannot read two databases or arbitrary time windows in one call. Keep temporal synthesis outside this single-scope item unless validated aggregate evidence is supplied in input.

### Metrics and acceptance checks

Answer current package performance with cell counts/mean/top4/win and prevalence. Only claim a change after buffs when both windows' evidence is actually available; compare within-tier shifts and six-versus-lower gaps without attributing causality to simultaneous buffs. Missing pre-period data is not a zero change.

### Capability limits and preparation

A standard native dataset item selects one database; arbitrary metadata cannot provide an executable second data source. No automatic patch/time filter, difference-in-differences evaluator or guaranteed hotfix boundary. The single-scope runnable adaptation explicitly limits the temporal claim.

### Reference answer contract

Answer the player question from actual scoped results, identifying the observed packages and direction or unresolved comparison. Report the case-specific counts and outcome tradeoffs, and distinguish an unsupported estimate from zero. A legitimate supported result may favor either alternative. Historical provisional answers and online ranking numbers are not the benchmark's expected values.

Source: [TR-1-C03 original case](../../../2026-09-28-set18-player-needs/case-drafts/2026-09-29-approved-lanes/traits/lanes/tr-1/cases.md) · original status provisional/incomplete. Proposal lineage: none.

Adaptation: Retain the original player question, adding in dataset input that this run uses the selected scope and can answer current two/four/six-Defender performance; a before/after conclusion needs supplied pre-period evidence. The temporal requirement is tracked as a preparation gap rather than fabricated or silently dropped.

Original question: After the 18.3 buffs to Cassiopeia and her tanks, did her endgame boards get better outside six Defender, or is six Defender still carrying her results?
