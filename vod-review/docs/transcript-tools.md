# Transcript tools

The review player has two explicit, independent actions: **Distill transcript**
and **Find key moments**. Opening a video or tab never runs a model. Results
are saved by VOD Review, survive reload/restart, and remain readable when ChatTFT
is unavailable. Browser storage contains only source selection IDs and tab
preferences. The last audio transcript can be reopened without opening it automatically.

Distillation uses the existing ChatTFT prompt and one model call, preserving its
Markdown output. Raw HTML is disabled in the Markdown renderer. Key moments use
only timestamped speech and source metadata. Significance must be established by
the speaker; the assistant cannot supply its own TFT advice, inferred visual
facts, or gameplay grades. These actions do not depend on one another.

Audio-only transcript views show a notice that no video is available to play.
Key moments show source-grounded explanations and expandable original excerpts.
Every supporting range has a review-relative timestamp and **Show in transcript**
control. The transcript tab preserves individual segment text, silence gaps,
overlaps, and fractional times, and provides the exact original plain text with
Copy. Audio-only views show times as text and have no playback callback.

Timestamp buttons seek in review-relative seconds with playback enabled. Online
adapters add `source_start_seconds` once: review second 12 in a source starting
at 300 seeks source second 312. The OCR manual offset does not apply. Early
clicks are queued until local/YouTube/Twitch playback is ready. The panel stacks
under playback below 1440px and occupies 340px alongside it on wider screens;
its content scrolls independently. Existing round analysis remains available.

## Configuration and prerequisites

Standalone VOD Review defaults to no LLM connection. To enable both actions:

```bash
export VOD_CHAT_TFT_BASE_URL=http://127.0.0.1:8300
uv run vod-review-start --port 8000
```

Use the address of your actual ChatTFT backend. Desktop supplies its discovered,
owned backend URL, including through WSL; it does not use a fixed ChatTFT port.
VOD communicates only over HTTP, without reading ChatTFT databases or importing
its Python modules. Shared-media storage can be disabled with `TFT_MEDIA_DIR=`;
these tools and their saved outputs continue to work.

Speech recognition still requires an Offline copy. Saved transcripts and both
supported LLM actions work in Online mode. Legacy text-only recognition supports
distillation; explicitly retranscribe a video to obtain timing for key moments.
Audio-only legacy sources must be reimported. Empty speech never calls a model.
An empty valid moments list displays “No critical moments were identified in
this transcript.”

Both applications enforce a 64,000 estimated source-token budget using the named
`o200k_base` tokenizer and a 10 MiB UTF-8 input ceiling, without truncation,
chunking, or summarization. The tokenizer needs its standard tiktoken encoding
cache on first use. This budget cannot guarantee every configurable model's
context limit; provider errors remain failures. Key-moment segment IDs are
`s000000`, `s000001`, etc., taken directly from the stored array index.

## Ownership and persistence

ChatTFT owns prompts, configured model selection, typed Pydantic output, and SDK
execution. Its catalogue explicitly registers `transcription_pipeline` (Markdown)
and `find_key_moments` (structured ranges), both version 1. Increment versions
when prompts, input construction, or output contracts change; saved versions
remain readable and changes never automatically regenerate results.

VOD's `backend/transcript_tasks/` owns its catalogue adapter, source snapshots,
SQLite attempt history, async HTTP client, workers, and validation of upstream
results. `db.init_db()` creates `transcript_task_runs` and its history/partial
active-run indexes. Lifespan owns workers and the client. At most two HTTP model
requests execute at a time; accepted excess attempts remain queued. Source hash
checks before execution and completion prevent results attaching to changed
text. Canonical hashes cover original text, language, and raw segments,
distinguishing `null` legacy timing from silent `[]` results.

Success is reusable only for the same source hash and task version. Explicit
reruns create new rows; failed reruns preserve previous successful output. A
short SQLite transaction reuses active work atomically. It never spans HTTP.
Queued/running rows interrupted by restart fail with a manual retry message;
requests are never automatically retried. Closing a browser does not stop work.
Shutdown cancels and awaits local workers. A 600-second upstream timeout can
leave the upstream model call running; a manual retry starts a new attempt.
Local cancellation does not promise upstream cancellation or exactly-once work.
Video deletion retains the existing saved-transcript/shared-resource behavior.

VOD resolves validated inclusive segment ranges into `start_seconds`,
`end_seconds`, and exact concatenated original segment text before persistence.
The end is the maximum end in that slice, retaining overlapping speech. Model
output never supplies playback times or quotations. Unknown/reversed references,
refusal, missing output, extra fields, and malformed envelopes fail the whole run.

## HTTP API

| Endpoint | Result |
| --- | --- |
| `GET /api/transcript-tasks` | Supported definitions, per-task availability and reason |
| `POST /api/transcriptions/{id}/tasks/{name}` | `{ "rerun": false }`; 202 queued/running or 200 reused success |
| `GET /api/transcriptions/{id}/tasks` | `active_run`, `latest_run`, `successful_run` per task and current hash |
| `GET /api/transcript-task-runs/{id}` | One persisted attempt |
| `GET /api/transcriptions/{id}?include_segments=true` | Public deterministic segment IDs and timing |

The default transcript response remains text-only. Internal database reads and
shared-media publication retain raw segment objects without public IDs. Unknown
identities/tasks return 404; unfinished/untimed prerequisites return 409;
malformed/empty/oversized source returns 422; unavailable ChatTFT returns 503.
Saved success can be reused while ChatTFT is unavailable.

## Validation

Focused backend tests use disposable SQLite stores and mocked upstream HTTP,
exercising the production routes and service. Frontend tests exercise explicit
actions, source switching, failed reruns, highlights, Markdown safety, and
playback adapters. `tests/browser/journeys.mjs` runs real VOD task endpoints with
a deterministic upstream boundary through transcription, both tasks, seeking,
source switching, backend restart, and restored saved results at wide/narrow
viewports. See [suite validation](../../tft-chat/docs/development/testing-and-evals.md).

Schema/runtime tests stub the SDK and separately validate source references.
The synthetic `find-key-moments` evaluation suite covers decisions, uncertainty,
corrections, repeated passages, irrelevant speech, missing visuals, and embedded
instructions. Assistant-only prompt evaluation does not exercise the task's
`output_type` contract. Offline validation does not establish live model quality.
Paid evaluation, real Whisper/GPU inference, hosted dataset writes, and external
online playback require separate explicit validation.
