# Decision-aligned investigations

This change assesses `skill-structure-brainstorming.pdf` and
`skill-structure-brainstorming2.pdf` against the current repository. The PDFs
are proposals, not executable requirements. Their cited benchmark results are
not evidence that a particular design improves ChatTFT; the implementation
below is justified by inspectable request paths and reproducible query cases.

## Assessment

The first analysis is strongest on choosing evidence that answers the player's
actual question. It correctly identifies the mandatory three-delta sweep in
itemization, conflicting quick-ranking instructions, report quotas, and sample
count labels that overstate confidence. Its distinction between observed final
boards and earlier player decisions is essential. A small flat playbook
catalog fits this repository, but introducing a new investigation record,
separate method loader, or larger catalog needs evidence of an unmet need.

The second analysis adds a valuable engineering principle: enforce comparison
semantics in code where possible. Its proposed shared-shell comparison tool is
largely already implemented by `compare_cohorts(target, baseline, shared)`,
including complement mode, overlap reporting, suppression, and eligible
lobby-clustered intervals. Its proposal also overreaches in places: overlapping
intervals are not a proof of equivalence; final-level cuts do not make an
earlier decision causal; and illustrative HP/roll thresholds cannot become
recommendations without evidence. A generic confounder sweep would recreate
the unnecessary-query problem it criticizes.

Both reports favor decisions over a topic hierarchy. Neither establishes that
adding a hierarchy, critics, specialist agents, automated learning, or example
retrieval would outperform the existing graph with coherent instructions.

## Alternatives considered

| Option | Decision and reason |
| --- | --- |
| Prompt cleanup only | Necessary, but leaves a real same-holder query gap and an eval path that omits skills. |
| Hierarchical skill selection | Keep the three existing flat skill identities. The current catalog is small; a tree would add routing without resolving comparison semantics. |
| New item/shell comparison tools | Extend the existing structured cohort filter instead. Shared-shell comparisons and statistics already exist. |
| Persistent investigation state or planner/critic graph | Defer. Existing run history carries evidence; no demonstrated need warrants new orchestration or mandatory model calls. |
| Worked-example retrieval or learned skills | Defer until curated traces and repeated behavioral evaluation justify the maintenance and token cost. |
| Shared instruction preparation plus occurrence-bound filters | Implement. It repairs concrete gaps while preserving existing tool, evidence, and graph contracts. |

## Resulting behavior

The root and analyst establish the requested question, constraints, population,
and useful next observation. A lookup can stop after answering the question.
Follow-ups need a material unresolved question; no skill requires every delta
tool. Conclusions can be supported, inconclusive, limited by unavailable
evidence, or partial because the investigation budget was reached. These are
behavioral instructions, not a deterministic guarantee of model judgment.

The three existing skills now supply focused investigation, interpretation,
and itemization guidance. Current item effects and other game facts remain
reference material. Responses preserve user constraints and distinguish
associations from timing or causal claims. The final responder retains evidence
references without mandatory table lengths or hypothetical result examples.

For a third-item question, `rank_unit_loadouts` can retain the two fixed items
with `item_1` and `item_2` and require `item_count=3`. For an explicit cohort
comparison, `UnitCondition.required_items` and `excluded_items` constrain the
same unit occurrence as its star and completed-item count. Previously, separate
unit and item conditions could match different copies of the same champion.
The new correlated predicates use the existing anonymous occurrence key;
there is no database migration, new public identifier, or changed sample floor.

Every requirement that must refer to one copy belongs in one `UnitCondition`
on each side. Separate conditions, including those in `shared`, still apply at
board grain. A board with two qualifying copies can belong to both cohorts;
the existing overlap report remains authoritative. See
[Query Cohorts](../tool_groups/query_cohorts.md) for exact semantics and examples.

## Integration and evaluation

All application execution surfaces retain `domain.assistants.Assistant` from
`origin/asst-runtime`: chat, direct API and CLI, transcript stages, Specs drafts,
and captured evaluations. `Assistant.prepare()` selects resources once using
its private definition snapshot. SDK callbacks render permitted resources at
every model step and handoff depth. There is no second preparation or factory
path for this feature.

Eligible recipients are assistants other than `chat` that use repository
context or explicitly name one or more skills, including an analytical
assistant invoked directly as the root.
Selection uses the union of their skill allowlists; rendering enforces each
recipient's permissions again. An omitted allowlist permits the discoverable
catalog; an empty list denies skills. The final responder permits only the
interpretation skill. Graphs without eligible recipients skip skill selection.
The caller system prefix still applies only to the root. Transcript-only graphs
skip reference and workflow selection.

Captured eval candidates replace only durable prompts in the isolated registry.
Explicit empty overrides remain empty. Task wrappers, frozen model settings,
activity hooks, invocation-local evidence, and execution provenance use the
existing `AssistantInvocation`. Resource selection and model execution share
one event loop. Historical bundles without captured graphs remain readable but
need a fresh export and an explicit database target before live execution.
Do not compare historical scores that omitted selected workflows directly
with new scores; rerun both candidates through the same path and data scope.

The [decision workflow evaluation guide](../development/decision-workflows.md)
describes the new cases. Compare the previous and revised prompts using the
same model, active data scope, budgets, and repeated trials. Inspect decision
alignment, retained constraints, denominator correctness, uncertainty, and
whether additional calls changed the useful answer. Do not score adherence to
one exact query sequence as a substitute for those properties.

Automated tests verify SQL membership on duplicate-holder boards, multiplicity,
exclusion, bounds, schema discovery, shared chat/eval assembly, nested handoffs,
allowlists, follow-ups, and resource isolation. They do not establish improved
player decisions or lower production latency. No live model comparison or
production database query is required to run these deterministic regressions.
