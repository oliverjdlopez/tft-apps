# Natural Langfuse workspace validation

Validated against self-hosted Langfuse **4.35.0** on September 15, 2026.
The ordinary workspace remains at `http://localhost:15500`. Browser/model
acceptance also used a separate disposable Compose project with a local mock
OpenAI endpoint.

## Migration audit

The before/after identity audit retained all eight dataset IDs, 54 item IDs,
12 historical experiment IDs and item roots, 84 historical scores, and 21
existing prompt versions. New prompt versions and experiments were additive.
Source-observation/source-trace links were unchanged. Repeating migration and
startup created no duplicate cases or grading resources.

All 182 original assertions appear in
`evals/langfuse/migration-manifest.json`; new snapshots retain their original
definitions and thresholds. Ten obsolete skill cases are archived, all twelve
skill definitions remain exportable, and the four known context failures remain
active. No historical numerical equivalence is claimed for consolidated rubrics.

## Executed checks

| Check | Result |
| --- | --- |
| Evaluation, configuration, and tracing regressions | 78 passed |
| Snapshot validation and offline deterministic fixture | Passed; 8 suites, 54 cases |
| Native mock scheduling | All five profiles passed both successful/failing calibration cases |
| Native browser editing | New cases, candidate prompts, and evaluator versions saved through the UI |
| Application comparison and replay | Two variants, including captured conversation input, completed native grading and frozen replay |
| Human review | Failed native score reasoning inspected; acceptance/category annotations saved |
| Development capture | Real streamed chat exported to the development environment and captured with source links |
| Tracing | Nested subprocess operations, per-call usage, prompt associations, and concurrency isolation verified |
| Timeout | Completed generation and handoff evidence survived termination; root recorded execution failure |
| Small live calibration | Transcript cleanup passed its native terminology evaluator at 1.0; real generation usage/prompt linkage verified |
| Frontend | 23 tests passed; production build succeeded with the existing large-chunk advisory |

The focused command is:

```bash
uv run --extra evals pytest -q evals/langfuse/tests tests/test_langfuse_execution.py tests/test_evaluation_catalog.py tests/test_langfuse_tracing.py tests/test_config.py
```

The browser CI job runs `browser-smoke.mjs`, `native-judge-smoke.py`,
`development-smoke.py`, `browser-review.mjs`, and `trace-timeout-smoke.py` under
`evals/langfuse/tests/`. It exports reports, frozen definitions, nested
observations, scores, and annotations before stopping its temporary deployment.
The manually dispatched live workflow also exports its complete workspace.

## Existing repository failures

The full run with `--continue-on-collection-errors` reported **448 passed,
7 skipped, 13 failed, and one collection error**. These existing failures are
outside the evaluation migration:

- `test_assistant_access.py` imports removed `assistant_reachable_names`.
- Database instrumentation expects removed `_rds_iam_target`.
- Two chat tests expect an older tool inventory.
- Three ingestion configuration tests expect removed `DEFAULT_CONFIG_PATHS`.
- Five RDS ingress tests assume configuration not supplied by their mocks.
- The module-cycle check reports `domain.tools.presentation.models → utils → models`.
- The update-tables CLI test supplies a mock with an outdated call signature.

The existing assistant workflow page also calls `data_analyst` terminal; current
source and evaluation cases route it through `final_responder`. This migration
preserves the implemented graph.

See [onboarding](langfuse-onboarding.md), [content and recovery](langfuse-content.md),
and [execution and tracing](langfuse-execution.md) for the resulting workflow.

## Backend Playground adapter (2026-09-16)

Verified the native prompt **Playground → Fresh playground** path against local
Langfuse 4.35.0. Selected `ChatTFT backend: chattft/unit_expert`, changed the
unsaved System message, added a User message, and submitted once. The reply
honored the draft's `ADAPTER_LIVE_CHECK` prefix and called the real `rank_units`
tool against `chat_tft_dev_set18_beta3` (192,344 boards in its active scope).
The trace exposed the draft, answer, two assistant model turns, database tool
arguments/results, context-selection call, timing, and costs. The trace URL now
selects the root observation directly because the v4 trace overview has no I/O.
Playground output is plain text in this version, so inspection URLs must be
copied into a tab; no Langfuse frontend fork is required.

Validation: 93 passing tests across `evals/langfuse/tests`,
`tests/test_langfuse_execution.py`, and `tests/test_langfuse_tracing.py`;
`chat-tft-evals validate` retained eight suites and 54 cases. Added native
Playground coverage to `browser-review.mjs` for the isolated mock CI deployment;
the local browser acceptance used the real configured backend instead of
rerunning that entire isolated deployment workflow. No saved prompt versions,
dataset items, or baselines were changed by this smoke run.
