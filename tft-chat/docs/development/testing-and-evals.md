# Tests and evaluations

## Setup and commands

Run suite validation from the suite root. Application environments stay independent.

```bash
uv sync --project tft-chat --locked --extra evals --extra compositions --group test
uv sync --project vod-review --locked
npm --prefix tft-chat/app/frontend ci
npm --prefix vod-review/frontend ci
npm --prefix desktop ci
python scripts/test_suite.py --tier offline --coverage
python scripts/test_postgres.py
```

Use `uv sync --inexact` when adding tools to an existing environment whose optional
packages should be retained. Use fresh temporary environments for exact lockfile
verification. The runner never installs/prunes dependencies. `--component
chat|vod|desktop` narrows offline runs; `--list` prints commands without execution.
Every run writes JUnit inventory, coverage, screenshots and `report.json` beneath a
unique ignored `.runtime/validation/<tier>-<component>/<run>/` directory. Captured
command and fixture-server logs go to suite `dev/logs/validation/`; VOD and browser
trace files go to `dev/traces/validation/`. The run report links diagnostic paths.
Frontend reports are in each frontend's ignored `coverage/`. There is no percentage
gate. Media, OCR caches, optional frame/box output and Drive-token coordinates stay
scoped to the run; inherited developer OAuth settings are disabled.

## Validation tiers

| Tier | Contract |
| --- | --- |
| `offline` | Unit/adapter, local HTTP/subprocess, frontend/build, desktop, authored baseline and offline fixture checks; PostgreSQL tests are deselected explicitly. |
| `postgres` | Complete isolated `RDS_TEST_*` target ending in `_test`; missing target, zero inventory or skipped integration tests fail. |
| `browser` | Built frontends, pinned Playwright, disposable servers, real Chromium interactions and artifacts. |
| `native` | Linux Electron, local fixture workspace and real process lifecycle; CI uses Xvfb. |
| `pdf` | Explicit `eval-pdfs` and native Pango/font dependencies; rendering checks cannot skip. |
| `gpu` | Explicit CUDA/cuML acceptance; checks cannot skip. |
| `external` | Opt-in real YouTube/Twitch embedding; depends on external availability. |
| `windows` | Opt-in native Windows/WSL acceptance through the existing harness. |

PR CI runs offline, PostgreSQL, browser, PDF and a separate native job. The
isolated Langfuse browser job retains mock-model coverage. External playback,
Windows/WSL, GPU, real inference and paid evaluation remain operator-selected.

`python scripts/test_postgres.py` owns a fresh PostgreSQL 16 Docker container
on an ephemeral loopback port, saves its logs and removes only that container.
It never reuses application targets or Compose volumes. PostgreSQL selection
uses the transitive `_pg_schema` fixture, and required integration rejects skips.

## Authored regression baselines

`evals/baselines.json` pins authored contracts to immutable snapshots.
`python -m evals validate` from ChatTFT validates native exports and authored
baselines. `python -m evals.baselines snapshot <suite>` resolves the reviewed hash.
Input, requirements, grading and case identity must agree. Remote identifiers,
export timestamps and item ordering do not constitute authored changes.

Langfuse remains editable. Its later exports cannot silently replace reviewed
regressions. Accepted changes update authored source, a successor snapshot and
baseline manifest together. Historical snapshots remain immutable. Context-response
regex checks are narrow smoke diagnostics rather than semantic accuracy grades;
negative examples challenge echoes, wrong quantities, contradictions and omissions.

The root manual workflow uses `python -m evals.baseline_run` to capture current
assistant definitions over pinned cases before paid dispatch. Local validation
never edits hosted content. `python -m evals.validation_fixture` exercises the
real offline path with a disposable catalog instead of writing tracked files.

## Behavioral ownership

Analytics tests protect anonymous facts, exact holder/loadout constraints,
suppression and clustered comparisons. Older set fixtures are intentional for
portable arithmetic and historical migration compatibility. PostgreSQL complements
SQLite for transaction-specific behavior. Resources/assistants cover discovery,
permissions, exact reads, captured graphs, handoffs and cancellation; a real SDK
subprocess executes against a local mock model. Fresh interpreters and static
runtime import analysis protect initialization boundaries.

Shared media acceptance runs both independent interpreters through real HTTP
boundaries. Python-produced stream events run through the actual JavaScript parser
with Unicode and every transport chunk width, supplementing jsdom UI tests.

## Flowchart editor validation

```bash
npm --prefix tests/browser ci
tests/browser/node_modules/.bin/playwright install chromium
python scripts/test_suite.py --tier browser
```

The existing smoke server owns disposable SQLite workspaces and empty assets,
without production startup or RDS. It covers pointer gestures, grouping, collapse,
layout, bends, clipboard, undo/redo, reload and 400-node/800-edge worker completion.
`FLOWCHART_PERFORMANCE=1` adds machine-sensitive responsiveness assertions;
functional assertions always run. Linux native acceptance uses
`xvfb-run -a python scripts/test_suite.py --tier native` or an existing display.
See [desktop setup](../../../docs/desktop.md) for native environment boundaries.

## Application journeys and independent oracles

The browser tier extends the existing smoke with real production-bundle journeys
at 1440px and 390px. Chat traverses HTTP routing, the real SDK, registered ranking
SQL over synthetic SQLite data, evidence resolution, rendering, navigation/reset,
and cancellation on view reload. VOD uploads generated media, draws a crop,
decodes/processes frames with deterministic inference, seeks to a round, publishes
a transcript readable through ChatTFT, and reopens persisted results after a backend
restart. Flowchart covers revision conflicts, rejected-save recovery, export and
library persistence. External model/inference boundaries alone are substituted.
Browser builds explicitly set an empty `VITE_API_BASE` to use their fixture origin,
matching the desktop proxy; standalone VOD builds retain their existing default.

Hypothesis checks compare cohort SQL with an independent occurrence-count oracle,
one-slot simulations with exact probability, irregular presentation timestamps
with integer scheduling, and UTF-8 byte fragmentation with the JavaScript parser.
Examples are reproducible; minimized regressions are stored in the run artifacts.
PostgreSQL additionally races two real connections saving the same revision and
requires exactly one winner. No application data or operational rebuilds are used.

Native acceptance now uploads and decodes a generated video, verifies seeking,
retains a chat draft across view switches, and proves all owned ports close. Its
suite/media coordinate is disposable, including when launchers enforce suite-owned
storage. The Windows tier invokes `tests/test-wsl.mjs` from an existing WSL setup,
which supplies context to the native Windows harness. A missing bridge fails
explicitly. Neither Windows nor external playback is implied by Linux results.

## Semantic grader calibration

`evals/datasets/semantic-calibration.json` contains proposed criterion-level labels
for synthetic factual answers, decisions and source-faithful distillation. Correct,
contradictory, incomplete and overconfident outputs are separate candidates. These
are judge-calibration examples, not assistant quality measurements or current TFT
gold. Human review must set the corpus review status and reviewer before it can
be consumed with `--require-reviewed`.

From ChatTFT:

```bash
python -m evals.calibration
python -m evals.calibration --grades /absolute/path/to/grades.json
```

The first command validates the corpus and reports `awaiting_grades`. Grades have
`evaluator: {name, version}` and a `grades` array of objects containing `case`,
`candidate`, `criterion`, numeric 0..1 `score`, and nonempty `reason`. Missing,
duplicate, unknown or nonfinite grades fail. Reports include the corpus SHA-256,
evaluator identity/version, existing 0.8 threshold, per-kind confusion counts,
agreement and explicit disagreements; they never promote labels automatically.

An explicitly invoked external adapter can be supplied with `--allow-paid
--judge-command <executable> <arguments...>`. It receives the corpus's sources,
criteria and candidate outputs as JSON stdin, with expected labels removed,
and returns that same grades document on stdout. Execution is bounded to ten
minutes. Tests exercise this adapter with a local process only and deliberately
inject one false positive and one false negative into the calibration calculation.
No paid judge accuracy is inferred from those plumbing tests.

## Optional configured database smoke

`CHAT_TFT_RUN_CONFIGURED_DB_SMOKE_TESTS=1` explicitly opts into the independent
read-only application database smoke. The suite runner disables this option;
verify its target before invoking it separately. It does not replace isolated
PostgreSQL validation. Do not run operational ingestion or projection rebuilds.

## Historical validation

[Archived reports](testing-history.md) retain older counts, commands and failures;
they describe dated checkouts rather than current blockers. See
[evaluation execution](langfuse-execution.md), [content](langfuse-content.md) and
[the migration record](../../../docs/migration.md) for runtime ownership.
