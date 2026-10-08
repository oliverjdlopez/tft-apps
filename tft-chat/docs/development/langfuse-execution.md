# Langfuse execution, scoring, and tracing

The Custom Experiment webhook freezes cases, prompts, evaluator definitions,
and rules before submitting durable work. Its default payload is deliberately
small:

```json
{"variants":[{"name":"baseline"}]}
```

Set top-level `"assistant": "unit_expert"` in that JSON to start every variant
in the run with a different registered assistant. Omitting it uses the dataset's
default assistant. The selected assistant determines the reachable prompt graph
and is retained in the frozen snapshot, including replay. This is separate from
`variants[].prompts`, which selects instruction versions for reachable assistants.

Advanced options include named model/prompt variants, reachable handoff prompt
overrides, subsets, repetitions, historical dataset versions, and offline/live
selectors. Each variant/repetition creates a separate experiment named
`baseline · <timestamp> · r1`. Job IDs and snapshot hashes live in metadata.
Export and replay remain maintenance actions in the advanced payload and CLI.

The root datasets `end-to-end` and `data-analysis` accept only string inputs.
The seven former intake prompts are now cases in `end-to-end`, marked with
`metadata.scoring: "none"`. Those cases skip SDK checks and native quality grading;
completion still requires an SDK result without an execution error. Scored cases
in the same experiment retain their existing acceptance requirements. Historical
execution-only suite snapshots remain readable.

## Acceptance

Python retains regex semantics, tool ordering, argument matching, paired results,
handoff ownership, resolver provenance, and selector metrics. Natural-contract
experiments publish each diagnostic plus Boolean `execution_success` and
`contract_pass`. The experiment output is the actual assistant answer or
structured task result; selectors return selected content or skill identities.
Latency, errors, usage, and diagnostic evidence belong in observations/metadata.

Five native Langfuse evaluators own quality grading: `answer_quality`,
`scope_honesty`, `rolldown_quality`, `terminology_preservation`, and
`signal_retention`. They return numeric 0–1 scores with explanations and use a
0.8 acceptance threshold by default. Original case-specific thresholds are
preserved. Rules sample every matching experiment-item root and filter by dataset,
quality profile, and successful execution. They exclude fixture and ordinary
development observations. Startup seeds missing resources through public APIs;
a durable resource-ID registry preserves subsequent UI edits.

An execution is not a completed evaluation. After execution the service saves an
`awaiting_scores` checkpoint. Reconciliation reads native experiment roots and
scores, detects evaluator changes, and publishes `attempt_pass` only when all
required conditions are known. Missing scores, invalid results, ambiguous
multiple grades, execution errors, and definition drift cannot pass. A grade must
identify the frozen evaluator, evaluator version, and evaluation rule. Scored
assistant cases require a quality profile; null metadata cannot disable the
quality gate. The grading
deadline is ten minutes after execution, with bounded polling. A restart resumes
reconciliation without repeating assistant or judge calls. Deterministic final
score IDs prevent duplicate final scores. Interrupted executions still require
explicit replay because their external calls cannot safely be retried.

Native score configuration names have a 35-character limit. Longer diagnostic
names receive stable hash suffixes; `original_check_name` and exported
`grading.score_names` preserve their full identities.

`weighted_score` remains available when reading legacy reports. It is not the
natural workflow's decision metric; every required check must pass.

## Automatic Markdown artifacts

Completed dataset jobs automatically write a private Markdown artifact to
`evals/langfuse/.runtime/artifacts/<job-id>.md`. A configured
`LANGFUSE_RUNTIME_DIR` relocates this directory with the runner's other state.
Each experiment variant/repetition contains its selected frozen prompts, full
final responses, and tool calls in recorded order beneath each response.
Arguments are rendered as nested Markdown lists, including explicit nulls;
tool return values are excluded. Structured prompts and outputs are rendered
as lists, while text prompts and responses are preserved verbatim.

The execution report now retains argument-only tool captures before entering
`awaiting_scores`, so grading can resume after a restart without retrieving
tool arguments from Langfuse. `JobStore.finish()` exports when execution and
grading reach a terminal `completed` or `failed` outcome, including grading
timeouts. Export-only requests and still-pending jobs do not produce a report.
Early failures produce an artifact with the selected prompts and explicit
missing-response notes; uncaptured tool arguments are distinguished from a
captured trace containing no calls. Interrupted executions retain the existing
explicit-replay requirement.

`GET /jobs/<job-id>` exposes `result.markdown_artifact` with `status: "written"`
and the absolute file `path`. Export failures instead record `status: "failed"`
and an `error`, without changing the evaluation outcome or discarding results.
The native completion status event includes the same report. The CLI `run`
path also exports automatically and prints this field in its result JSON;
runs without asynchronous grading use the comparison group ID as the filename.
Files are replaced atomically and remain ignored runtime artifacts. Older
saved jobs do not acquire tool arguments retroactively.

## Traces

The documented OpenInference OpenAI Agents integration records actual nested
agent, generation, tool, and handoff observations. W3C trace context crosses the
isolated-process boundary; child workers flush completed spans. Isolated natural
workers use Langfuse as their sole Agents exporter. Opt-in application tracing
retains existing application processors. Real generation
usage replaces the synthetic aggregate generation for natural-contract runs.
A parent-aware span processor links each generation to its owning assistant's
frozen prompt version. Full presentation arguments remain visible in tool
observations; judges receive a bounded presentation/evidence summary.

The worker retains the existing process-group timeout. On timeout the experiment
root records the execution error. SIGTERM gives the worker up to two seconds to
flush completed spans before process-group termination; the currently open child
operation may remain unfinished. Completed observations exported before termination
remain available.

## Development capture

Set `[chat] langfuse_tracing = true` to opt into local conversation export. It is
false by default. Install the `evals` optional dependencies and provide
`LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY` through the
environment. Missing instrumentation or exporter failures do not fail chat.

Development roots use the `development` environment and the same `messages`
input contract as end-to-end experiments. In Langfuse, add a useful observation
to the chat dataset, retain the source observation link, and author its expected
requirements. Ordinary conversations do not trigger native quality rules or
become benchmark cases automatically.

## Human review

Open `ChatTFT review` under annotation queues. Use `human_acceptance` and
`failure_category` to distinguish application failures, evaluator mistakes,
obsolete expectations, and accepted results. Correct the reference or evaluator
in the native UI, then run a new comparison with identical frozen cases and
grading definitions for baseline and candidate.

## Native Playground adapter

`evals/langfuse/playground.py` registers authenticated `/v1/models` and
`/v1/chat/completions` routes on the host runner. Seeding installs the owned
**ChatTFT backend** OpenAI-compatible connection with base URL
`http://experiments/v1`, the existing private runner credential, and registered
`chattft/<assistant>` model names. Judge connections are untouched. Compose
explicitly allowlists the internal `experiments` hostname for LLM connections;
additional configured hosts remain supported.

The Docker proxy streams completion responses over the private Unix socket.
Request validation translates text system/developer messages into one
request-scoped base-prompt override, preserves user/assistant history, and
executes `evals.worker` in a fresh subprocess using the existing eval database
boundary. No production prompt or saved Langfuse version is modified by Run.
An absent system message uses the repository base; an explicit empty system
message supplies an empty base. SDK RunConfig applies supported generation
settings across the graph without changing registered tools or handoffs.

Each request creates a `chattft-playground` parent observation and propagates its
trace context into instrumented SDK execution. Draft text is recorded as an
unversioned override rather than falsely attributed to a saved prompt version.
The returned answer appends a trace link; the trace's output retains the clean
assistant answer. Usage totals cover all model calls in that graph. SSE includes
keepalive comments while work runs, a completed answer, finish event, optional
usage event, and `[DONE]`; this is completion streaming, not token streaming.

At most four Playground workers run concurrently, independently of dataset job
concurrency. Each has a 180-second subprocess deadline and ten agent turns.
Closing the browser does not cancel a started worker: it finishes or times out,
retains its concurrency slot, and exports its trace. Invalid requests fail
before execution, capacity returns 429, and execution failures expose a private
trace link without forwarding raw provider/connection errors. The adapter does
not implement Responses API, custom client tools, images, or structured output.
