# Decision workflow evaluations

`evals/datasets/decision_workflows.json` is a schema-v3 seed for eight
player-facing TFT analysis situations. It covers a quick frequency lookup, a
fixed-shell Bard third-item comparison, Vi and Death's Defiance, discovering
comp shells without a 2-star Amumu, an audit of a surprising result,
suppression, an inconclusive comparison, and the evidence limits of a
prospective roll-versus-level choice.

Each case uses the normal `chat` assistant path and the native
`answer_quality` profile. Its requirements judge whether the answer helps with
the decision, preserves the comparison conditions, reports available sample
and uncertainty context, and stays within the evidence. Cases do not prescribe
a tool sequence or encode an exact item ranking, cohort count, or outcome as
verified gold. The named unit and item scenarios are prompts for evaluation;
`evidence_status: gold_unverified` records that their data support has not been
checked against a particular active scope.

Run the focused contract test from `tft-chat/` with:

```bash
uv run pytest -q tests/test_decision_workflow_suite.py
```

The test validates the bundle and its assistant references without calling a
model or database. Register the dataset in the local snapshot catalog without
starting Langfuse from `tft-chat/` with:

```bash
uv run --extra evals python -m evals create-dataset \
  --name decision_workflows \
  --dataset-name decision-workflows \
  --assistant chat \
  --items evals/datasets/decision_workflows.json \
  --description "Player-facing TFT decision workflow evaluations." \
  --max-turns 12 \
  --register-only
```

This writes a content-addressed local snapshot and catalog entry only. The seed
is readable and validated, but it has no captured assistant graph and does not
select an evaluation database. Before live execution, create a fresh run bundle
that captures every variant's current assistant graph and selects an explicit
evaluation database. The captured-definition and database requirements are
described in [Langfuse execution](langfuse-execution.md). A hosted Langfuse
dataset or model-backed experiment is a separate operation.
