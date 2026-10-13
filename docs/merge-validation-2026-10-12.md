# Merge validation: 2026-10-12

Validated `dev` at `ad8ab42`, followed by the working-tree repairs described
below. The initial ChatTFT Python run had 25 failures. After the worker/test
repairs and the authorized import refactor, one unresolved test failure remains. No paid evaluations, ingestion, production database smoke
tests, or projection rebuild commands were run.

## Final results

| Check | Result |
| --- | --- |
| Desktop JavaScript, `npm test` from `desktop/` | 80 passed |
| Desktop Python, `../tft-chat/.venv/bin/python -m pytest -q` from `desktop/` | 17 passed |
| ChatTFT Python, `.venv/bin/python -m pytest -q --tb=short` from `tft-chat/` | 1,017 passed, 1 failed, 20 skipped |
| ChatTFT frontend, `npm test` from `tft-chat/app/frontend/` | 139 passed |
| ChatTFT frontend, `npm run build` | Passed |
| VOD Python, `.venv/bin/python -m pytest --import-mode=importlib -q` from `vod-review/` | 239 passed |
| VOD frontend, `npm test` from `vod-review/frontend/` | 52 passed |
| VOD frontend, `npm run build` | Passed |
| Offline `dummy_assistant` evaluation | 1 case passed |
| Offline `skill_selection` evaluation | 2 active cases passed |
| Full evaluation validation and offline `context_selection` | Accepted legacy failure: missing Riven corpus content for `exact_unit` |

Checking every catalog entry independently confirmed that 12 of 13 suites pass
structural and semantic validation; only `context_selection` fails. These checks
validate definitions, not live answer quality.

Evaluation commands use `.venv/bin/python -m evals` from `tft-chat/` with
`validate` or `run --suite <name> --offline`. Offline runs created local reports;
their generated snapshot copies were moved out of the checkout and the catalog
was restored so validation does not change authored evaluation definitions.
Command logs and generated snapshot copies are under
`/tmp/tft-merge-validation/` on the validation machine.

The sandbox denied local sockets. Desktop and Python suites were rerun with
socket access; those results appear above. Both frontend builds reported large
bundle warnings. Python reported dependency deprecations. The skipped tests
remain unvalidated; no live browser, native Windows UI, OCR accuracy benchmark,
hosted Langfuse grading, or paid model quality evaluation is claimed.

## Repairs

- Removed the obsolete `require_explicit` argument from the evaluation worker.
  The merged resolver already implements per-field `RDS_EVAL_*` fallback to
  `RDS_*`. Existing acceptance tests now execute captured graphs through the
  real SDK and a local mock model server for both coordinate sources.
- Updated database fallback tests for the moved `evals.assistant_execution`
  module, valid captured definitions, and current metadata/trace signatures.
- Patched the composition worker at the service boundary actually imported by
  the API lifespan, preventing the unit test from starting a real supervisor.
- Removed a mock of the retired IAM helper and matched the engine test to the
  merged 15-second connection/pool limits.
- Isolated fake EC2 tests from local dotenv and sync preferences; AWS calls
  remain mocked.
- Updated ingestion tests to exercise the canonical project INI loader and
  configured endless-cycle values, and aligned maintenance mocks with the
  current optional DSN argument.
- Selected an active case for preflight rejection tests. Archived cases are
  intentionally excluded from semantic validation. Kept probability regex
  coverage against an immutable historical snapshot containing the retired
  case, without restoring it to the active dataset.

## Remaining decisions and accepted failures

### Context-response acceptance criteria

`tests/test_context_response_suite.py::test_suite_is_registered_portable_and_has_exactly_thirty_single_checks`
fails because the catalog export and portable seed differ. They contain the
same 30 case identities and questions, but all 30 deterministic regex checks
differ. For example, the export accepts any of `riftbeast`, `cinderling`, `gromp`,
or `pebbles`; the seed requires all ten roster members. Expected outputs also
differ (`null` versus an empty string), alongside export metadata and order.

Choose whether the portable fact requirements or the broader exported checks
should govern future runs, then reconcile the seed/export/test. Neither set of
acceptance criteria was weakened or overwritten during validation.

### Import dependencies: resolved

All six circular dependency groups were removed through code ownership changes:

- Context rendering moved into provider utilities, retaining its public re-export.
- Assistant tool wiring accepts a registry and no longer imports the package facade.
- Reference classification coordinates scalar/accelerated paths from `reference.py`.
- Composition comparison helpers receive loaded boards from the display layer.
- Transcription shares models/helpers and passes the local downloader into the
  shared-media adapter.
- Langfuse graph capture, prompt publication, transport construction, and diagnostic
  seeding now live with their owning operations. Pure adapters remain in utilities.

The original cycle check passed before changing its diagnostics. The enhanced
check reports every cycle group, continues to include deferred runtime imports,
and excludes imports used only for static typing. All 16 fresh-process import
checks passed. The final full Python run passed 1,017 tests, with 20 skipped and
only the existing context-response mismatch failing. This includes captured SDK
execution against a local mock model and offline shared/local download coverage.
Offline fixture and skill evaluations also passed again using copied snapshots
and separate runtime directories under `/tmp/tft-merge-validation/import-evals/`.
No active catalog entries changed during this follow-up.

### Context-selection benchmark corpus

The `exact_unit` case asks "What role does Riven play?" and requires a context
snippet containing the literal Markdown `**Riven**`. The current corpus contains
no Riven snippet. The user confirmed that this content was intentionally removed
with older compatibility material and accepted the resulting test/evaluation
failure. The benchmark and corpus remain unchanged.
