# Shared UI migration validation

Validation performed on 2026-09-23. Application changes are confined to frontend
source/configuration, desktop CSS, and documentation. Backend contracts, streams,
model calls, database schema, and persisted data are unchanged.

## Automated checks

| Checkout | Clean install | Tests | Production build |
| --- | --- | --- | --- |
| ChatTFT `app/frontend` | `npm ci` | 81 passing | Vite passes |
| VOD Review `frontend` | `npm ci` | 44 passing | TypeScript + Vite pass |
| Wisps `frontend` | `npm ci` | 33 passing | TypeScript + Vite pass |

The desktop Node suite passes 50 tests, including immutable Windows asset staging,
retained views, configurable composition visibility, reload ordering, recovery, shortcuts,
and owned service cleanup. Production builds retain Vite's large-chunk advisory;
no bundling or code-splitting work was added to this interface migration.

Frontend regression coverage includes shared-dialog cancellation/focus return,
file event forwarding, disabled upload controls, boolean checkbox events without
accidental form submission, native radio selection semantics, keyboard section navigation, sidebar persistence,
workflow category resets, typed tool payloads/default omission, composition
high-sample confirmation, help focus, chat stream parsing, and A2UI interactions.
Existing video tests cover import settings, processing/polling, round selection,
annotation queues, frame stepping, and Wisp review. The Wisps polling fixture now
returns a Wisp frame for `/frame?` instead of an unrelated video record; production
frame rendering was not weakened to accommodate the old mock.

The routed Python checks were also run:

```bash
UV_CACHE_DIR=/tmp/chattft-uv-cache uv run --no-sync pytest -q \
  tests/test_chat_service.py tests/test_start_cli.py \
  tests/test_tracing_service.py tests/test_config.py
```

They report **17 passed, 2 failed**. Both failures are existing tool-registry
expectations in `tests/test_chat_service.py`: the tool list omits
`rolldown_probabilities`, and trace metadata expects only
`request_additional_context` while the configured assistant exposes more direct
tools. Neither Python source nor these tests changed in this migration. The full
Python suite was not run.

## Browser evidence

Chromium captured 14 primary states at **1440, 1024, and 390px** (42 images):
Chat; Assistants; Tasks; Status; Models; Tools; Raw API; Prompt tuning; Specs;
Compositions with family details; Rolldown setup; VOD Analyze; VOD Annotate; and
Wisps. Each has document width equal to the viewport and no page JavaScript
errors. Automated WCAG 2 A/AA and 2.1 AA checks report no violations in the 14
primary desktop-width fixture states. This is bounded automated coverage, not a
claim of a complete accessibility audit.

Nine additional captures cover populated Rolldown Insights, Distributions, and
Run explorer. Fixture output was produced by the existing Python simulator with
a synthetic roster. Heatmap/3D switching, pointer rotation, Reset view, analysis
navigation, and champion controls were exercised. These views have no page-wide
overflow at any of the three widths; the Run explorer checks report no automated
WCAG A/AA violations.

Video states use a generated 960×540 test video, including crop and annotation
canvases. Video and canvas bounds match within one CSS pixel at each viewport.
The screenshots exercise original-video fallback and Wisp frame/OCR inspection.
No user video or third-party download was used.

Six shell captures show the actual plain-HTML startup and recovery pages with a
fixture state callback. The navigation remains 48px high and contains all seven
destinations, with local horizontal scrolling at narrow widths.

The local screenshot gallery is written to the task's `shadcn-review/index.html`
artifact, alongside images and the primary matrix's `results.json`. Screenshots
and fixture payloads are review artifacts, not committed production assets.

## Unavailable live checks

Native Windows GUI validation could not run: the computer-use helper rejected the
WSL workspace URI, and the installed Windows Electron executable failed before
launch with `WSL ... UtilBindVsockAnyPort ... socket failed 1`. Passing Linux tests
and Chromium shell screenshots do not establish Windows Electron behavior.
Repeat native tab switching, shortcuts, staged-asset loading, startup, and recovery
on a Windows session with working WSL interoperability.

The browser checks mock HTTP responses. Real model streaming, database access,
YouTube/Twitch imports, OCR processing, and Google Drive uploads were not run.
Their existing event/payload behavior remains covered by the frontend suites;
external-service smoke validation remains a separate live check.
