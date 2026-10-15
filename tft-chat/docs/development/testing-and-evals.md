# Tests and Evaluations

The current resource implementation uses `domain.resources` exclusively. The
provider package, generic provider protocol, selector execution/scoring families,
legacy resource aliases, and provider-specific tests are removed. Current run
configs do not accept the removed selector option. Local successor snapshots keep
assistant cases and grading rules while removing obsolete selector configuration,
prompts, and captured selector definitions. No hosted content is changed.
The combined resource, assistant, tool, import, and evaluation regression run
passed 372 tests, including all Langfuse adapter tests and local SDK subprocesses.
No paid evaluations or frontend interaction were exercised.

`python -m domain.resources` validates 141 resources/views, and
`python -m evals validate` passes for 11 assistant suites and 142 cases. The former
selector `exact_unit` preflight no longer exists. The lower dated validation
reports describe earlier checkouts, not current blockers.

The [2026-10-12 merge validation](../../../docs/merge-validation-2026-10-12.md)
records the current cross-application results, repaired worker/test regressions,
and unresolved evaluation-content and import-policy decisions. It supersedes
the older failure counts recorded below.

`tests/test_repository_consistency.py` enforces acyclic runtime imports, including
imports deferred inside functions. It reports all strongly connected groups in
one failure. Imports guarded by `TYPE_CHECKING` or `typing.TYPE_CHECKING` are
excluded, while their runtime branches remain checked. Sixteen isolated process
checks import the affected resource, assistant, composition, transcription, and
Langfuse entry modules first, so pytest's already-loaded modules cannot conceal
initialization-order failures. Run these checks from the ChatTFT root:

```bash
.venv/bin/python -m pytest -q tests/test_repository_consistency.py
```

## Pytest and CI

The Python CI gate is:

```bash
uv run pytest -q
```

The CI job also installs Node 22, runs the locked frontend install, executes
Vitest/jsdom browser tests, and creates the Vite production build before the
Python suite. Run the same frontend checks locally with:

```bash
cd app/frontend
npm ci
npm test
npm run build
```

GitHub Actions supplies PostgreSQL 16 and an isolated `RDS_TEST_*` target.
`conftest.py` checks connectivity, creates the runtime schema once, and resets
the tables for every database-backed `conn` fixture. Those fixtures skip when
the test database is absent or unreachable, so a local green run may cover
less than CI; the skip count records that distinction.

Most unit tests use fakes and monkeypatching and need neither network access
nor credentials. There is currently no repository formatter, lint command,
coverage threshold, or static type-checking CI step. Frontend tests use jsdom
and Testing Library to exercise the stream parser, application tabs, and the
three evidence displays. `tests/test_evidence.py` verifies pre-rounding capture,
reference isolation, compatible specifications, suppression, bounded coverage,
and SDK-tool-to-stream precision. Run it with the assistant and chat tests for
changes to evidence ownership or transport. Grader execution evidence recognizes
`present_evidence` and legacy `present_inline_data` calls from historical traces;
frozen historical snapshots retain their original prompt and tool names.

Invocation preparation is covered by `tests/test_assistant_runtime.py`, alongside
`tests/test_assistants.py`, `tests/test_chat_service.py`, and `tests/test_task_service.py`.
These use isolated resource libraries and runners to verify metadata-only
preparation, exact reads, dynamic root and nested handoff policy, definition
snapshots, fresh evidence/activity, task input
wrappers, synchronous/asynchronous entry points, and failure cleanup without
paid calls. `evals/langfuse/tests/test_assistant_workspace.py` additionally executes
a captured graph in a real SDK subprocess against a local mock model server;
this needs localhost socket access but no PostgreSQL or paid model calls.

The Assistant encapsulation checks passed 194 focused tests, including that
subprocess acceptance test and the model-default snapshot regression. Seven failures in `tests/test_evaluation_catalog.py` reproduced
on an untouched export of dev commit `e07f3b6`: stale inventory counts, stale
preflight expectations, a mock missing the `require_explicit` argument, and four
cases referencing a removed probability fixture. The offline validator also reaches the same `exact_unit` missing-corpus-gold
failure on the changed tree and that untouched dev export. No live grading,
database tools, ingestion, or projection rebuilds were used for this validation.

Current cohort and delta registry coverage is in `tests/test_cohort_facts.py`
and `tests/test_openai_tools.py`. `tests/test_cohort_loadouts.py` verifies that
unit stars, item counts, and required/excluded items match the same occurrence,
including duplicate holders, repeated items, cross-scope isolation, and overlap.
These checks use anonymous SQLite fixtures and strict tool-schema discovery;
they do not query the configured application database.

Every test has a 60-second POSIX alarm guardrail spanning fixture setup, the
test call, and fixture teardown. A stall fails with its node ID and the active
Python traceback instead of blocking the suite.
Set `PYTEST_TEST_TIMEOUT_SECONDS` to change the repository default, or use
`@pytest.mark.timeout(seconds)` for a targeted override. A marker value of `0`
explicitly disables the guardrail for that test.

### Development database benchmark coverage

`tests/test_db_benchmarks.py` checks workload definitions and CLI defaults,
input/result validation, insufficient-data classification, successful-sample
statistics, timeout cleanup, and the database-free `--list` path without
connecting to PostgreSQL. `tests/test_db_benchmarks_integration.py` seeds a
synthetic ready fact population and aggregate rows in the isolated `RDS_TEST_*`
database, then checks benchmark discovery, holder-conditioned queries, result
grouping, and read-only behavior. It never targets the configured application
database and skips locally when the isolated target is unavailable.

Run both suites with:

```bash
uv run pytest -q tests/test_db_benchmarks.py tests/test_db_benchmarks_integration.py
```

CI probes its isolated PostgreSQL target before pytest so a configured but
unreachable database cannot turn these integration checks into silent skips.

## Configured database smoke tests

`tests/test_configured_db_smoke.py` makes representative calls through the
registered model-facing tools and their normal read-only database boundary. It
checks rankings, exact-name resolution, and bounded SQL aggregate results using
stable structural and metric invariants rather than patch-sensitive ranking
values.

The smoke suite targets the typed `RDS_*` application database and is skipped
unless an operator explicitly opts in. It never uses the truncating
`RDS_TEST_*` fixtures. Run it only after verifying the configured application
target:

```bash
CHAT_TFT_RUN_CONFIGURED_DB_SMOKE_TESTS=1 \
  uv run pytest -q --log-cli-level=INFO tests/test_configured_db_smoke.py
```

The tools enforce a read-only PostgreSQL transaction, minimum public sample
sizes, row limits, and the aggregate-table allowlist during these calls. The
INFO logs report each tool's elapsed time and bounded result summary, plus the
public unit, item, or trait names used to verify the response.

## Langfuse evaluations

Langfuse is the separate evaluation workspace. Start it with
`uv run --extra evals python -m evals up` and open <http://localhost:15510>.
Workflow datasets, prompt versions, native evaluators, and annotations are edited
in its UI. See the [browser walkthrough](langfuse-onboarding.md). Native Custom Experiment buttons call the local Python service, which
runs the real assistant graph and publishes traces, scores, and comparisons.

The initial copied workspace had six datasets and 56 cases, including 11 archived
cases. On 2026-10-01, an explicitly requested unit expert import added 17 active
cases to the existing `chattft/unit-expert` dataset. The 2026-10-06 cutover added
17 item, 18 composition and 17 trait cases, and refreshed the unit cases from
the latest authored source. The suite now has eight datasets and 125 cases in
total, including 69 active expert cases and the original 11 archived cases.
Active workflow inputs retain their authored schemas. The local catalog
retains immutable historical snapshots plus registered workflows. See the suite
[migration record](../../../docs/migration.md) for exact inventory and verification. Reusable trace, selector, worker,
and database logic lives
in `evals/`; platform integration and exported definitions live in
`evals/langfuse/`. Every run exports its frozen inputs into content-addressed
snapshots for Git review. Production prompts remain repository-owned.

The [decision workflow suite](decision-workflows.md) adds eight locally
registered cases for useful player answers, retained comparison constraints,
and evidence limits. Its authored requirements prescribe no fixed query
sequence and claim no verified outcome gold. The seed is loadable offline;
live execution requires a fresh captured graph and an explicit evaluation
database target through the existing export/run path.

```bash
uv sync --locked --extra evals
uv run --extra evals python -m evals validate
uv run --extra evals python -m evals run --suite dummy_assistant --offline
uv run --extra evals pytest -q tests/test_langfuse_execution.py evals/langfuse/tests
```

CI retains the Python and frontend gates, adds catalog/execution/HTTP tests and
the credential-free fixture, and starts an isolated Compose stack for the native
browser workflow. The live evaluation workflow remains an explicit dispatch
using the `evals` environment. HTTP tests require local event-loop/socket access;
Docker and browser integration checks require their corresponding runtimes.

See [the evaluation guide](../../evals/README.md),
[deployment and backups](langfuse-local.md),
[content and snapshots](langfuse-content.md), and
[execution and scoring](langfuse-execution.md) for the exact contracts.

### Existing coverage gaps

Selector corpus cases and compatibility checks have been removed. Resource
coverage now lives in `tests/test_resource_library.py` and the assistant runtime,
permission, and captured-execution tests. The deterministic fixture remains
credential-free.

Historical Promptfoo results are retained untouched. The
[compatibility history](native-promptfoo-compatibility.md) describes the retired
integration, not current commands. The ChatTFT in-app Evals API/editor remain removed.

Recent saved evaluations can be reviewed without model calls using
`uv run --extra eval-pdfs chat-tft-export-eval-pdfs`. This creates combined and
per-dataset Markdown/PDF pairs from the latest finished runs. See the
[export command and options](langfuse-execution.md#export-recent-evaluations-as-markdown-and-pdf).
Run its offline checks with
`uv run --extra eval-pdfs pytest -q tests/test_export_eval_pdfs.py`.

The [natural workspace validation record](langfuse-validation.md) documents migration identity checks, browser acceptance, native mock scheduling, timeout evidence, and existing repository test failures.

The 2026-10-02 [retirement of the older checkout](../../../docs/retiring-tft-suite.md)
preserved its complete 69-case authored Set 18 collection under
`eval-brainstormings/2026-09-30-code-grounded/`, 16 additional immutable snapshots,
and its historical catalogue under `evals/langfuse/archives/tft-suite-20261002/`.
These copies preserve authoring and historical definitions; they do not replace
the active catalogue or register cases in the hosted workspace. The existing
17-case unit expert import and other local work remain intact.

## Context and response smoke checks

The [30-case context/response suite](context-response-smoke.md) targets `chat`
with one fact-oriented response regex per question and no quality judge. It is
registered as `context_response_smoke`, with portable schema-v3 JSON and CSV
seed copies and the native dataset name `context-response`. The regexes check
key answer facts while trace inspection covers context selection and retrieval
completeness.

## Flowchart checks

Run `uv run pytest -q tests/test_flowchart_api.py tests/test_flowchart_persistence.py tests/test_entity_assets.py`,
`npm --prefix app/frontend test`, and `npm --prefix ../desktop test`. The API tests
use a disposable SQLite table and a temporary `gameplans/` directory; the
persistence test uses the isolated `RDS_TEST_*` target and skips when it is
unavailable. `app/frontend/src/flowchart/Flowchart.test.jsx` stubs `fetch` and
covers workspace creation, palette search, drops onto plans and empty canvas,
autosave revisions, conflicts, and read-only JSON import. See
[Flowchart](../apps/flowchart.md).

## Composition workbench checks

Run `uv run --extra compositions pytest -q tests/compositions`,
`npm --prefix app/frontend test`, `npm --prefix app/frontend run build`, and
`npm --prefix ../desktop test`. Shared JSON fixtures validate Pydantic/Zod acceptance,
unknown-field rejection, duplicates, null outcomes, score semantics, and denominators.
Regenerate exported JSON schemas/fixtures with
`uv run python scripts/export_composition_contracts.py`.

Adapter tests independently exercise the same snapshots and serialization contract.
Persistence unit tests use disposable SQLite files; PostgreSQL integration and owned
child-process tests use the isolated `RDS_TEST_*` target and skip when unavailable.
They verify immutable reruns, separate full-population results, interruption recovery,
worker failure, cancellation, and unchanged source analytics. The opt-in native
Electron workspace smoke additionally checks Compositions visibility, retention,
renderer isolation, and cleanup. See [the adapter contract](../architecture/compositions/adapter.md).

Suite CI lives at `../.github/workflows/ci.yml`. Desktop Python tests have their
own `../desktop/pytest.ini` with the suite root on the import path.


## Flowchart editor validation

Run the focused document/storage checks, the full frontend suite/build, and
suite desktop tests:

```bash
uv run pytest -q tests/test_flowchart_api.py tests/test_flowchart_persistence.py
npm --prefix app/frontend test
npm --prefix app/frontend run build
npm --prefix ../desktop test
uv run pytest -q ../desktop/tests/test_backend.py ../desktop/tests/test_vod_backend.py
```

The API tests use in-memory SQLite and temporary export files. They verify v1
reads do not rewrite either source, v2 nested save/import/export/library round
trips, invalid/cyclic parents, bounded routing metadata and optimistic revisions.
PostgreSQL checks skip when the isolated `RDS_TEST_*` target is unavailable.
Frontend tests cover commands/history, editor keys, clipboard, nested groups,
collapse proxies, cyclic search/focus, locks, reconnection, insertion, geometry,
read-only views, no-save loading and stale layout responses.

For real production-worker smoke, first build the frontend, then run the
provided disposable server in one terminal and the Playwright script in another:

```bash
uv run python -m uvicorn --app-dir tests flowchart_smoke_server:app --host 127.0.0.1 --port 8429
# Use an existing Playwright install or install it in a temporary directory.
FLOWCHART_PLAYWRIGHT_MODULE=/absolute/path/to/playwright/index.mjs node tests/flowchart_browser_smoke.mjs
```

`tests/flowchart_smoke_server.py` uses a temporary SQLite store and export root,
empty asset catalog, and the built frontend; it does not start production
lifespan, connect to RDS, or edit live workspaces. The smoke imports disposable
fixtures, checks empty-canvas deselection after a marquee, short right-click
menus, right-drag/hold selection preservation, popup targeting and dismissal,
then groups/collapses a connected branch, arranges it, edits a long guard,
drags a manual bend, copies/pastes, undoes/redoes and reloads to verify document
and personal-view persistence. `FLOWCHART_SMOKE_URL` can change its loopback URL;
`FLOWCHART_SMOKE_SCREENSHOT` optionally saves a screenshot. The script also
imports 400 elements/800 connections, verifies worker progress and responsive
search during routing/layout, and rejects console/page errors. The synthetic
fixture allows overlap warnings where clear routes or labels are impossible.
A Chromium smoke does not validate native Electron/Windows shell behavior;
report that boundary separately from desktop unit tests.

## Specs workspace acceptance

See [assistant workspace](assistant-workspace.md) for the draft lifecycle and API.
Focused acceptance tests cover SQLite revisions, invalid saves, source/runtime
conflicts, optional files, rollback/restart recovery, restore/import, bounded local
trials, exact graphs, and durable duplicate-submission handling.
`evals/langfuse/tests/test_assistant_workspace.py` also executes the real SDK in a
bounded worker against a local deterministic HTTP model, with an explicit `_test`
database identity. It exercises frozen models/reasoning, handoffs, tools, wrappers,
and instruction assembly without connecting to PostgreSQL or spending tokens.
Frontend coverage exercises saved actions, conflicts, imports, and result links.
Browser smoke verification should use disposable specs and mocked optional services.
Live hosted grading and database tools are separate checks; report them explicitly
when unavailable. Never use ingestion or projection rebuilds as validation.

## Captured evaluation execution checks

Live assistant experiments and Playground require captured definitions; historical
snapshots remain readable. Run focused checks from the ChatTFT root:

```bash
uv run --extra evals pytest -q tests/test_assistant_runtime.py tests/test_assistant_access.py tests/test_assistants.py tests/test_langfuse_execution.py tests/test_evaluation_assistant.py tests/test_task_service.py tests/test_spec_service.py evals/langfuse/tests
```

Local HTTP mock
acceptance needs localhost socket access, but no paid model calls or PostgreSQL.
Captured configured models and SDK run overrides are recorded separately.

Migration validation passed 284 focused tests, including the real SDK subprocess
against the deterministic local HTTP model, with seven baseline failures deselected.
The added direct-attempt missing-capture regression passed separately. All seven
excluded failures reproduced on the saved untouched baseline: catalog inventory,
stale preflight expectations, four removed probability-case lookups, and the
natural-workspace conversion lookup for `comp-expert`. The offline fixture passed;
full catalog validation still reports missing corpus gold for `exact_unit`.
Checks used the existing temporary isolated Python environment because this checkout
has no `.venv`. No paid calls, hosted content edits, ingestion, projection rebuilds,
or production database tests were used.

Decision workflow integration on top of `2cef657` passed 378 focused tests,
including the real SDK subprocess against the deterministic local HTTP model.
The six remaining failures match the migration baseline: stale tool preflight
expectations, four removed probability-case lookups, and the natural-workspace
conversion lookup for `comp-expert`. The inventory checks now cover all 14
historical bundles unchanged plus the eight new decision workflow cases.
Full catalog validation still reports missing corpus gold for `exact_unit`.
The combined checks cover runtime and access policies, chat and task services,
captured evaluations, Specs trials, skill providers, cohort/loadout SQL, tool
schemas, and evidence. They used the existing main-checkout Python environment;
no paid model calls or production database queries were made.
