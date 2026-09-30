# ChatTFT evaluations with Langfuse

Langfuse owns the evaluation workspace: edit datasets and prompt versions, start
experiments, inspect trace evidence and scores, and compare model/prompt variants.
A separate Python experiment service invokes the real ChatTFT assistant graph and
preserves specialized deterministic checks while native evaluators grade quality. Normal ChatTFT
conversations continue using repository assistant specifications.

## Start the workspace

Install Docker Engine with Compose, then run:

```bash
uv sync --locked --extra evals
uv run --extra evals python -m evals up
```

Open <http://localhost:15500>. The initial login is `evals@chattft.local`; its
password is the `LANGFUSE_INIT_USER_PASSWORD` value in the private
`evals/langfuse/.env` file. Keep that file with the persistent volumes. Startup
creates missing datasets/prompts/evaluators/review resources and native experiment buttons; repeating startup
does not overwrite UI edits. `chat-tft-evals` is the equivalent installed command.

The platform runs separately from ChatTFT's application. See
[local deployment and backups](../docs/development/langfuse-local.md).

## Work entirely in the browser

Use the [browser walkthrough](../docs/development/langfuse-onboarding.md): choose
one workflow dataset, add application input and expected requirements, save a
candidate prompt, launch the native Custom Experiment webhook, compare readable
outputs and scores, inspect a failed trace, and record a human judgment.

The default payload is `{"variants":[{"name":"baseline"}]}`. Model overrides,
handoff prompt candidates, subsets, repetitions, and export/replay are advanced
options. Every label resolves before execution. Native quality evaluators grade
successful experiment item roots; ordinary development conversations are excluded.

## Snapshots and replay

Every run exports its complete definitions into `langfuse/snapshots/` before
execution. Bundles are named by their SHA-256 content hash; the catalog points
to the latest exported definition for each suite. Review and commit those files
normally. Nothing automatically commits or pushes. Existing bundles are immutable;
conflicting catalog edits are rejected.

Set `"action": "export"` in the native run configuration to export without running.
Set `"action": "replay", "snapshot": "<sha256>"` to rerun a frozen bundle. Replay
uses its original cases, prompts, and settings, even after subsequent UI edits.
Snapshots freeze definitions, not model randomness or the underlying database.
Raw results and durable job state remain outside tracked snapshots.

See [content and snapshot contracts](../docs/development/langfuse-content.md) and
[execution and scoring](../docs/development/langfuse-execution.md).

## Validation and CI

```bash
uv run --extra evals python -m evals validate
uv run --extra evals python -m evals run --suite dummy_assistant --offline
uv run --extra evals pytest -q
uv run --extra evals python -m evals down
```

`down` preserves volumes and credentials. Fixture validation works without
Docker, Langfuse credentials, or a database. The CI browser job starts an isolated
Langfuse stack; the live workflow remains an explicit dispatch with model and
typed evaluation-database credentials. See
[testing and evaluations](../docs/development/testing-and-evals.md).

The catalog contains 84 cases across nine suites, including the 30 context/response smoke cases and the intentionally empty
`analyze_transcript` suite. The
scored suites retain 86 deterministic assistant checks and 13 rubrics. The known
offline context failures remain `numeric_heading`,
`partial_heading_category`, `semantic_description`, and `semantic_unit_mechanic`.
Ten obsolete skill cases are archived with repair reasons and preserved original expectations.

Historical Promptfoo data in `evals/.promptfoo/` is retained untouched and is not
imported into Langfuse. The retired in-app Evals editor and `/api/evals` routes
remain retired. Assistant-spec suite discovery reads local snapshots and works
with Langfuse stopped.

The original hosted workspace has two root datasets: `end-to-end` (28 cases) and
`data-analysis` (seven cases). Both accept string inputs only. Normal startup
also seeds the 30-case `context-response` workflow; the other local suites
retain historical regression coverage without recreating deleted hosted datasets.

See the [context/response smoke suite](../docs/development/context-response-smoke.md)
for its 30 questions, single fact-oriented regex checks, portable JSON/CSV, and transfer
instructions. The new suite is additive and has no quality judge.
