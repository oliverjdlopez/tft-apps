# Test suite modernization and acceptance

The two implementation stages share one runner, dependency selection and authored
baseline registry. Application HTTP contracts and production assistant definitions
are unchanged. Historical evaluation snapshots remain immutable.

## Stage 1: repairs and consolidation

- Root CI installs the ChatTFT `evals`, `compositions` and `test` dependency sets
  explicitly. VOD retains its own locked environment. Both frontends have matching
  Vitest coverage providers; the browser harness has a separate pinned lockfile.
- `scripts/test_suite.py` declares offline, PostgreSQL, browser, native, PDF, GPU,
  external-playback and Windows/WSL tiers. Commands run from application-owned
  directories with unique reports, deadlines and process-group cleanup.
- PostgreSQL tests are selected by their transitive fixture requirements. A required
  tier rejects absent targets, zero test inventory and skips. The Docker helper owns
  disposable PostgreSQL 16 on an ephemeral port and retains logs after cleanup.
- Regression cases are pinned in `tft-chat/evals/baselines.json`. Source/baseline
  validation checks authored semantics independently of mutable native exports.
  Context-response uses a new fact-check snapshot with adversarial negatives;
  historical placeholders remain readable as historical definitions.
- The root manual live workflow captures current assistant definitions over pinned
  cases before explicit paid dispatch. Its CLI path has a credential-free acceptance
  test. Validation/offline fixture execution does not modify the tracked catalog.
- Existing browser and Linux Electron smokes are CI jobs. Duplicate adapter execution
  and incidental global inventory counts were removed. Current guidance is separated
  from archived validation history. Coverage is diagnostic, without percentage gates.
- Previously skipped integration tests were corrected to use test targets, explicit
  single-platform fake-Riot settings, the current insertion signature, the retained
  HDBSCAN adapter, and the current summary/full-assignment distinction.

## Stage 2: added capabilities

- Browser journeys run production bundles and real application routes at 1440px and
  390px. Chat uses the real SDK, SQL ranking and evidence handling with a local mock
  model. Cancellation is verified at the existing view-reload boundary.
- Flowchart journeys verify competing revisions, rejected-save atomicity, recovery,
  export/library persistence, an injected HTTP save outage and successful UI retry.
- VOD journeys upload generated media, draw a crop, run real decode/cache/processing
  with deterministic inference, seek with an offset, share transcripts with ChatTFT,
  and recover persisted analysis/transcripts after restarting the backend.
- Hypothesis compares cohort SQL against an independent occurrence counter, seeded
  one-slot simulations against exact probability, irregular frame sampling against
  integer scheduling, and byte-fragmented UTF-8 against the JavaScript parser.
- PostgreSQL acceptance races independent sessions saving the same revision and
  requires one winner. Native Electron additionally tests generated video playback,
  seeking, retained chat drafts and complete owned-process shutdown. Its suite/media
  coordinate is disposable rather than the developer catalogue.
- A synthetic semantic corpus supplies 18 proposed outputs across factual, decision
  and distillation examples. Calibration reports criterion-level false positives,
  false negatives, disagreements, corpus hash and evaluator version. Missing or
  ambiguous grades fail; expected labels never reach an external judge adapter.

## Commands and reports

See [the current validation guide](../tft-chat/docs/development/testing-and-evals.md)
for setup and all tier contracts. From the suite root:

```bash
python scripts/test_suite.py --tier offline --coverage
python scripts/test_postgres.py
python scripts/test_suite.py --tier browser
python scripts/test_suite.py --tier native --component desktop
python scripts/test_suite.py --tier pdf --component chat
```

Use an existing display for native acceptance, or prefix the command with
`xvfb-run -a`. To validate a clean Python dependency selection without pruning the
developer environment, set `UV_PROJECT_ENVIRONMENT` to a new temporary directory
when syncing, then supply that interpreter as `CHAT_TEST_PYTHON` to the runner.
Use `uv sync --inexact` when adding dependencies to a shared developer environment.

Each run writes its `report.json`, Python JUnit inventories, XML coverage, and
screenshots under `.runtime/validation/<tier>-<component>/<run>/`. Captured process
and fixture-server logs are stored in the suite `dev/logs/validation/` tree; VOD
JSONL traces and Playwright trace archives are stored in `dev/traces/validation/`.
The report links each command log and records the diagnostics directories, while
screenshots and coverage remain beside the report or in each frontend's `coverage/`.
The PostgreSQL helper's container log is also under `dev/logs/validation/` and its
path is recorded in the tier report. CI uploads reports and the suite/app `dev/`
diagnostic directories together. These ignored diagnostic directories retain
outputs even when assertions fail. `--list` is a read-only command inventory.

## Validation boundaries

Test data,
media, runtime stores, reports and coverage are ignored. No operational ingestion,
application projection rebuild, hosted dataset write or paid evaluation is part of
these correctness runs.

Semantic labels remain **proposed** until a human reviews and records the reviewer.
The local mock adapter validates grading mechanics, not judge accuracy. GPU/real
inference, external embedding, Windows/WSL and live judge calibration have explicit
entry points and must not be inferred from Linux/browser success. Existing Langfuse
Docker/browser CI is separate from the local acceptance runs; do not start its fixed
production project/ports against an existing developer stack for validation.

## Acceptance results — 2026-10-15

The implementation was validated with Python 3.13.13, Node 22.22.1, the pinned
Playwright 1.58.2 browser environment, Linux Electron, and disposable PostgreSQL 16.
The clean ChatTFT environment installed the exact locked `evals`, `compositions`
and `test` selections and collected the complete required suite successfully.
Both Python lockfiles pass `uv lock --check --offline`.

| Run | Measured result |
| --- | --- |
| ChatTFT Python in clean environment, with coverage | 1,032 passed; 10 optional skips; 11 PostgreSQL cases deliberately deselected |
| ChatTFT frontend with coverage | 140 passed; production build passed |
| VOD Python with coverage | 254 passed |
| VOD frontend with coverage | 55 passed; production build passed |
| Desktop JavaScript | 80 passed |
| Desktop Python/cross-application | 22 passed |
| Required PostgreSQL 16 | 11 passed, no skips, including competing-save transactions |
| Required PDF rendering | 8 passed, no skips |
| Existing Flowchart Chromium smoke | Passed, including the 400-node/800-edge fixture |
| Application journeys | Passed at 1440px and 390px, including injected HTTP failure/recovery and persisted transcript reopening |
| Linux Electron | Workspace smoke and real application lifecycle passed, including decoded 128×96 video frames, seeking, React draft retention and owned-port shutdown |
| Focused final oracles/calibration/workflow checks | 13 passed; includes real multibyte plaintext fragmented one byte at a time |
| Focused runner failure/isolation guards | 5 passed |

The six default test groups total 1,583 passing tests. Their 10 skips are four
GPU capability cases, four configured-application-database cases, and two optional
PDF cases absent from the clean ordinary environment. The separate PDF tier
executes rendering successfully. PostgreSQL was required and executed, not skipped.

Negative acceptance proved that an unreachable required test target produces errors
instead of skips; missing/duplicate/nonfinite judge grades and altered/missing
baseline references are rejected; unreviewed semantic labels cannot be promoted;
and hung owned processes are terminated with retained diagnostics. Expected negative
test failures are not application regressions. Existing deprecation/resource
warnings remain visible rather than suppressed.

Local artifacts include:

- `.runtime/validation/offline-all/20261015T115959-2476885/`: combined regression,
  backend coverage, JUnit and command logs.
- `.runtime/validation/postgres-chat/20261015T115558-2466016/`: required database
  acceptance; its owned container was removed and its log retained.
- `.runtime/validation/browser-all/20261015T120840-2509422/`: complete browser gate,
  screenshots and Playwright traces.
- `.runtime/validation/native-desktop/20261015T121312-2521925/`: final native decoded-
  frame and React draft acceptance with runtime version metadata.
- `.runtime/validation/pdf-chat/20261015T114817-2445068/`: actual rendering acceptance.

After the complete browser gate, the application journeys also passed with the
final explicit OAuth/cache/trace isolation and stronger decoded-frame checks.
Documentation links, Python compilation, immutable-snapshot preservation, lockfiles
and whitespace checks passed. CRLF files retain their existing line endings;
the whitespace check uses `git -c core.whitespace=cr-at-eol diff --check`.

Not exercised locally: GitHub-hosted job execution, the existing Langfuse Docker
browser stack, Windows/WSL, real GPU/inference, external YouTube/Twitch embedding,
or paid assistant/judge calls. Semantic labels remain proposed pending human review.
