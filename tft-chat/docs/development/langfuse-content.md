# Langfuse content and snapshots

Langfuse 4.35.0 owns workflow datasets, candidate prompt versions, evaluator
versions, experiment comparisons, and human annotations. Production assistant
prompts remain in the repository.

For adding or retiring assistants, use the
[spec management CLI](assistant-specs.md). Startup seeds missing assistant prompts
from current repository definitions and preserves existing hosted versions. Fresh
natural-dataset experiments resolve only the current reachable assistant graph;
historical snapshot prompt inventories do not recreate retired prompts. Explicit
prompt cleanup backs up all selected versions before deletion. Dataset retirement
and evaluator changes remain separate maintenance operations.

## Workflow datasets

| CLI alias | Native dataset | Cases |
| --- | --- | ---: |
| `chat` | `end-to-end` | 28 |
| `data_analyst` | `data-analysis` | 7 |
| `context_response_smoke` | `context-response` | 30 |

Normal startup seeds these three root-level datasets; an existing workspace's
`context-response-smoke` dataset was renamed in place to `context-response`,
retaining its dataset, item, and experiment identities. See the
[30-case context/response smoke suite](context-response-smoke.md) for portable
JSON/CSV and its one-fact-regex-per-case contract. The seven former
intake prompts are included in `end-to-end`. The nested `chattft/`, `internal/`,
`archive/`, and `set18-buildout` datasets were removed after backup and verified
copying. Local historical selector, transcript, and fixture snapshots remain
available for offline regression checks; normal startup seeds the active
workflows listed above. Test deployments can still seed the historical fixtures.

### Create another assistant dataset

Use the repository command to register a new browser-owned dataset. It creates a
schema-v3 snapshot and catalog entry, starts or updates Langfuse, seeds the
dataset and initial cases, configures its authenticated Custom Experiment button,
and adds its ID to existing native grading rules. Existing rule filters and
subsequent UI edits to cases remain intact. It refuses to change the setup while
an experiment is queued, running, or awaiting scores.
Run it before creating that dataset name directly in Langfuse; an existing dataset
without the ChatTFT string-item contract is rejected instead of silently reused.

```bash
uv run --extra evals python -m evals create-dataset \
  --name manual_probe --dataset-name chattft/manual-probe \
  --assistant chat --items /path/to/cases.json
```

`--assistant` is optional and defaults to `chat`. It sets the dataset's default
entry assistant; it does not lock future experiments to that assistant. In the
Langfuse Custom Experiment JSON, set `"assistant": "unit_expert"` to select a
different registered entry assistant for one run. Omit it to use the dataset
default. Prompt candidates are checked against the selected assistant's handoff
graph, and the selected assistant is frozen in the run snapshot for replay.

Omit `--items` to start with an empty dataset and add cases in Langfuse. Omit
`--dataset-name` to use `chattft/<name>`. `--database` supplies a suite default;
case `metadata.database` overrides it. `--register-only` writes and validates the
snapshot/catalog without starting Docker; run `uv run --extra evals python -m evals up`
and `uv run --extra evals python -m evals restart-runner` later to seed the
workspace and reload an existing runner. Repeating the command for an already registered suite does not
reimport its initial file or overwrite Langfuse edits.

The optional JSON is an array of cases, or an object with an `items` array:

```json
{
  "items": [
    {
      "case": "four_cost_units",
      "input": "Which four-cost units perform best in the scoped data?",
      "expected_output": {
        "requirements": ["Include sample sizes and average placement."]
      },
      "metadata": {"database": "tft_set_16"}
    }
  ]
}
```

The command assigns a stable `<suite>/<case>` ID and defaults scored cases to
`quality_profile: "answer_quality"`. For an execution-only item, set
`metadata.scoring: "none"` and omit `expected_output`. To use deterministic
checks without a judge, supply `metadata.deterministic_checks` and
`metadata.quality_profile: null` with a valid expected output. JSON ingestion
validates the whole definition before writing the catalog or contacting Langfuse.
It registers only assistants already present in the repository spec inventory.
Per-case `scope_id` selection is not implemented; tools still use the selected
database's active analysis scope.

## String item contracts

Schema-v3 dataset input is a single string:

```json
"Compare Riven and Jax in the scoped data."
```

The native input schema is `{"type":"string"}`. Objects (including `messages`
and `text` wrappers), arrays, and null inputs are rejected. In a JSON editor,
quote the string; the value itself is the user message. The execution adapter
supplies that text to the existing assistant worker. Normal application chat
and Playground conversation history are unchanged. Schema-v1/v2 snapshots retain
their original contracts for historical reading and replay.

Expected output remains reference text or an object containing `requirements`
and/or `reference`. Metadata carries descriptions, database selection,
`deterministic_checks`, `quality_profile`, and `quality_threshold`. Copying retains
original source trace/observation links and records `source_dataset` and
`source_item_id`; new datasets and items have new native identities.

The seven imported intake cases use `metadata.scoring: "none"` and omit expected
output. They run in the same experiment as the scored benchmarks but do not
invoke deterministic or native quality evaluators. Their execution status still
participates in experiment completion. To promote one to a scored benchmark,
remove `scoring: "none"` and add expected output. Other new chat cases inherit
normal answer-quality grading. Missing expected output alone never disables
grading.

`evals/langfuse/consolidation.py` builds a copy/delete plan from a complete private
workspace export. It rejects multi-turn inputs instead of flattening their roles,
verifies destination membership and content, remaps native evaluator dataset
filters, and rechecks source content before deletion. Backup and plan files belong
in private runtime storage, not Git. Deleting source datasets removes their native
history links from the workspace; the pre-deletion export is retained for audit.

### Keep cases from multiple TFT sets

In Langfuse, open **Datasets**, select a case, and add `database` to its
**Metadata**, preserving any existing fields:

```json
{"database": "tft_set_16"}
```

The name above is an example; use an existing PostgreSQL database accessible
through your configured `RDS_EVAL_*` connection. Pin old cases to their old
database and add new cases with the new database name. Both can remain active
in the same dataset and experiment. This setting applies to assistant cases;
context and skill selectors use repository content rather than a database.

Selection precedence is case `metadata.database`, suite `database`, then the
configured evaluation database. Missing or null values inherit the next level;
blank names and connection strings are rejected. Only the database name changes:
host, port, authentication, and credentials still come from the typed evaluation
target. Do not put connection URLs or credentials in case metadata or input.

Each attempt runs in its own worker with the selected database, including its
assistant handoffs and tools. Result metadata records the resolved `database`.
Exports freeze case metadata, so explicit database choices survive replay.
Cases without an explicit name retain the existing fallback behavior; pin them
before changing the configured default. Existing immutable snapshots are not
rewritten, and a snapshot pins a database name, not the contents of that database.
Database selection does not override `[chat] patch` or `[chat] set_number`.
Repository context and tools that use those settings still follow application
configuration; this feature selects the data connection, not a complete set-specific
runtime configuration.

`evals/langfuse/contracts.py` converts schema-v1 snapshots to schema v2.
`assertion_manifest` maps every old assertion to a native evaluator/reference
requirement or deterministic check, preserving thresholds, weights, and the
entire original definition. The checked-in `evals/langfuse/migration-manifest.json`
records the live dataset/item identities and all 182 assertion destinations. The fifteen rubrics map to ten `answer_quality`, two
`scope_honesty`, and one each of `rolldown_quality`,
`terminology_preservation`, and `signal_retention`. Consolidated scores are not
numerically equivalent to historical rubric scores.

## Export, migration, and recovery

```bash
uv run --extra evals python -m evals export-workspace /private/workspace-backup.json
uv run --extra evals python -m evals migrate --directory /private/migration
uv run --extra evals python -m evals migrate --directory /private/migration --apply
```

Migration exports first and stores a plan and per-item journal. Native renames
preserve dataset IDs; public item upserts preserve item IDs and historical
versions. A rerun skips verified writes, detects intervening edits, and checks
complete membership before applying schemas. The plan retains original dataset
names and complete item definitions for rollback review. Keep it with the
workspace backup and persistent volumes. Complete exports include nested
observations, per-call usage, prompt links, all score pages, and human annotations.
They contain authored content, not provider credentials.

Public APIs handle routine operations. The pinned native adapter handles
renames, webhook configuration, and archived-inclusive item enumeration: the
4.35.0 public item list returns active items only. Historical run links use the
v4 experiment APIs, not the retired dataset-run list endpoint.

## Reproducibility

New snapshots include schemas, dataset versions, exact prompt versions,
evaluator definitions/version IDs, rules, acceptance thresholds, and source/data
provenance. Old snapshots remain readable; an LF/CRLF checkout difference is
accepted only when its normalized bytes match the original hash. Immutable
history is never rewritten.

Prompt labels resolve before submission. The default uses `baseline`; the
initial migration labels the existing production-labelled prompt version, not
an arbitrary latest candidate. Changing a prompt in Langfuse never changes
production repository instructions.

Replay requires unchanged native evaluator definitions. Restore older evaluator
definitions into an isolated replay project when necessary. New exports include
dataset-name mappings so isolated replay can rebind project-local IDs only after
evaluator prompts, model settings, output contracts, variable mappings, and rule
behavior match. The result records the effective destination grading definitions;
same-workspace replay still requires the exact frozen evaluator versions. Evaluator drift
makes a result non-comparable and unable to pass. A passing experiment never
automatically becomes a reviewed baseline:

```bash
uv run --extra evals python -m evals review-baseline --snapshot <sha256> --reviewer "reviewer name"
```
