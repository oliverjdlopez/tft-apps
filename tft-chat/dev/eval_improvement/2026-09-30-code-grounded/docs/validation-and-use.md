# What can be benchmarked from this deliverable

The original lane/combined JSON files target the existing `chat` graph and native `answer_quality` profile. The later [expert definitions](../experts/README.md) target the corresponding available specialists, with `chat` retained for traits. They exercise evidence gathering, preservation of the question's constraints, analytical coverage and interpretation. They contain no fabricated gameplay winner, score, sample size, database name, stored entity identifier, frozen live result or fake Langfuse ID.

Importability, behavior scoring and factual gold are three distinct claims:

1. **Definition/import compatibility:** the existing importer normalizes every item and invokes its bundle/semantic validators. Our validator intercepts snapshot export and catalog reads, so this test does not register anything. It also checks supported tools, partial argument schemas and positive/negative synthetic trace witnesses. Synthetic traces test assertions, not gameplay answers.
2. **Investigation and answer coverage:** native trace checks enforce observable tool behavior, and the quality rubric evaluates the case-specific requirements. A passing tool-called check does not establish successful queries, valid cohort membership, sufficient sample size or correct numerical grounding. These remain material review criteria.
3. **Numerical gold:** the native judge's evidence mapping supplies a bounded summary/presentation extract, not every tool output. A compatible frozen aggregate reference or full-trace verification is needed to independently certify numerical fidelity. No real database/model run was performed, and no claim of measured benchmark performance is made.

## Execution population

Use a verified, ready, stable Set 18 standard-ranked analysis database. Record its data revision and actual collection scope privately with the run. The 18.3B questions need a genuinely compatible window; a normalized patch string does not establish the September hotfix interval. Verify configured repository context set and acknowledge the 18.1/18.2 baseline's rules freshness. `metadata.database` changes only the connection's database name; it does not freeze its contents or select a per-case scope. These datasets inherit the evaluation target rather than inventing one.

Run data preflight outside the evaluated answer. Missing facts, an unrelated scope, or mostly suppressed candidate cells are data-readiness failures, not evidence of poor gameplay alternatives. The inputs permit useful partial investigation, but generic refusal is not the intended benchmark answer when evidence is available. No helper in this deliverable rebuilds or mutates analysis data.

For strict original requirements such as no emblems anywhere, exact deployed capacity, equal whole-board resources, a complete composition partition or multi-window comparisons, the current public tools have gaps. Each rewritten case names the supported proxy and the stronger unmet condition. For a fully enumerated roster, requiring all N distinct identities and selecting the reportable board_size=N query row can certify stored-roster closure. Only that row’s outcomes carry the restriction; it does not fix occupied capacity or confer compare_cohorts intervals. Where the dataset input narrows the task to the supported proxy, its rubric must grade that visible task, not secretly demand the unavailable original restriction.

## Current Langfuse datasets

The user authorized integration, top-level naming and then distribution by the
original lanes. Current datasets are `item-expert` (17), `unit-expert` (17),
`comp-expert` (18) and `trait-expert` (17). The combined live dataset and active
catalog registration were deleted after all copies were verified. `meta-expert`
remains empty. See the [distribution receipt](../validation/expert-distribution.json)
for destination identities and snapshots, and [expert definitions](../experts/README.md)
for runner defaults and the limited tool-alternative adaptations. Earlier
[integration](../validation/langfuse-integration.json) and
[rename](../validation/dataset-flattening.json) receipts remain historical records.
No model evaluation was run.

For a fresh workspace, use the standard setup command with one expert definition,
for example:

```bash
uv run --extra evals python -m evals create-dataset \
  --name item-expert --dataset-name item-expert \
  --assistant item_expert --max-turns 40 \
  --items eval-brainstormings/2026-09-30-code-grounded/experts/item-expert/dataset.json
```

The expert suites inherit the configured evaluation target. Set
verified per-case `metadata.database` values in Langfuse if another database is
needed; re-running registration preserves existing hosted cases and suite defaults.
For a new suite, the existing `--database` option supplies that suite's default.
The original combined and lane JSON files remain authoring records. Do not
re-register the retired combined dataset or import duplicate copies of these
cases into the same benchmark.

The 40-turn starting budget is an authoring assumption, not a measured optimum. Multi-cell lanes such as IT-4 and composition discovery may need budget tuning after observing real traces. Compare variants at the same verified data revision and budget. The collection contains related carry/package questions; split by research family/source lineage rather than blindly treating 69 cases as independent player demands.

## Reproduce offline validation

From the repository root, using the installed environment without dependency or source writes:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=app/backend/src:app/backend:. \
  .venv/bin/python eval-brainstormings/2026-09-30-code-grounded/scripts/validate_datasets.py
```

This is an authoring-stage audit tied to the recorded source revision. It writes only the combined dataset and validation record inside this brainstorming run and contacts no database or Langfuse. Its preservation check permits only the original integration's catalog/documentation hashes. Subsequent authorized changes, including the top-level naming update, intentionally make that historical source check fail; the rename receipt and current registration tests validate the later integration. The pre-existing large disk report and `profiling/` are user-owned unrelated changes.

`scripts/build_reconciliation.py` renders coordinator translations into lane Markdown/JSON and the manifest/lineage records. It does not author lane datasets, overwrite original research or make runtime changes. Lane datasets were authored separately by delegated agents after those reconciliations existed.
