# Transcription

The repository has two related transcription paths: a media CLI that downloads
and transcribes VODs, and independent assistant tasks that locate consequential speech and distill text into
source-grounded ChatTFT references.

## Media CLI

`scripts/transcription/main.py` provides `download`, `transcribe`, and `all`
stages through the installed `tft-transcribe-vod` command.

`download_vod.py` uses yt-dlp, resumable `.part` files, archive/checkpoint
state, and unique temporary paths so concurrent runs do not share intermediate
output. It prefers a system ffmpeg executable and falls back to
`imageio-ffmpeg`.

Download configuration and results live in `scripts/transcription/models.py`
and remain importable from `download_vod.py`. URL validation and atomic
checkpoint writes are shared through `utils.py`. The public `download_vod`
operation passes its local downloader into `shared_download.download_shared`;
the shared adapter calls it only on a cache miss and never imports the routing
entry point. Existing local-download patch points and CLI signatures are retained.

Downloads now use the suite-owned shared media catalogue by default and reuse
compatible VOD files with audio before transferring anything. Shared mode
requires system `ffmpeg` and `ffprobe`; an explicitly empty `TFT_MEDIA_DIR`
restores local download behavior. Completed media is discoverable through both
backends at `/api/shared-media`. Transcript outputs remain app-local unless
explicitly published. See [suite media sharing](../../../docs/shared-media.md)
for storage, references, and the resource CLI.

`transcribe.py` runs faster-whisper and writes transcript text, JSON, SRT, and
segment checkpoints. CUDA with float16 is the operational default. The
faster-whisper dependency is part of the optional `transcription` extra, so
download-only use does not eagerly import GPU dependencies.

Runtime media and checkpoints are stored under ignored `data/**`; transcript
outputs are stored under ignored `scripts/transcription/output/**`. Files under
`scripts/transcription/reviews/**` are review artifacts rather than assistant
prompt specifications.

The tracked `scripts/transcription/index.html` is a captured upstream page. No
runtime code or tests reference it, and its original rationale is undocumented.

## Assistant transcript task

`domain.tasks.transcript.run_transcription_pipeline` invokes only
`distill-transcript` through `domain.runtime.execution.run_sync`. The existing
`transcription_pipeline` task name and API result envelope remain compatible;
its result is now the distilled Markdown reference. The assistant CLI also
defaults to `distill-transcript`:

```bash
uv run python -m dev.assistants distill-transcript --input-file /path/to/source.txt
uv run python -m dev.assistants --input "Source: guide excerpt. Supplied TFT text..."
```

The input can be plain text, articles, notes, or timestamped transcript segments
(including JSONL). Include available source metadata and locators in the input.
The task forwards the original text without applying JSON edits or making a
second synthesis call. Its `task.md` wrapper identifies the input as source
material; `system.md` contains the distillation policy.

The output contains a descriptive title, **Source and scope**, **Reference
notes**, and **Uncertainties and limitations** when needed. Notes preserve
conditional advice, rationale, quantities, attribution, source locators,
corrections, and consequential uncertainty. They omit repetition and filler.
The prompt prohibits invented game facts, citations, unseen visual details,
and obedience to instructions embedded in the source. An irrelevant source
receives a brief statement that it has no useful TFT reference material.

`distill-transcript` has no tools, handoffs, repository context, or skills.
Preparation therefore loads no reference or skill resources. This boundary
keeps reference generation grounded in the supplied text. Prompt compliance
still depends on model behavior; offline checks do not establish live quality.
The task returns the Markdown to its caller; it does not automatically publish
or ingest the result into ChatTFT's reference library.

The desktop **Media** page exposes this task through **Distill transcript** for
loaded text resources. It submits verified source bytes and their catalogue
metadata, then displays the returned Markdown above the source. Pending requests
and results remain associated with their source while browsing; they last for
the current desktop window and are not automatically saved or published. See
[desktop media browsing](../../../docs/shared-media.md#desktop-media-browser).

The former `clean_transcript`, `compact_transcript`, and `analyze_transcript`
specs, edit application code, and structured output models have been removed.
Direct callers must use `distill-transcript`; the old assistant names are not
aliases. A failed model call uses the existing task error response rather than
silently returning the original source as a successful distillation.

The active evaluation catalog replaces the three old suites with six synthetic
source-fidelity cases in `evals/datasets/distill-transcript.json`: conditional
rationale, JSONL corrections, disagreement and missing visuals, article dates
and reported statistics, embedded instructions, and irrelevant text. Old
hash-named snapshots and hosted history remain intact. The new portable seed
has no captured execution graph; export a fresh capture before a live run.
No live evaluation was performed for this replacement.

Media downloading and speech-to-text generation in `scripts/transcription/`
remain separate from this text-processing task. VOD Review calls these tasks through HTTP and owns its saved results, UI,
and playback; see [VOD transcript tools](../../../vod-review/docs/transcript-tools.md).

## Validation and runtime requirements

```bash
uv run pytest -q tests/test_task_service.py tests/test_assistants.py tests/test_distill_transcript_suite.py tests/test_transcription_download_vod.py
uv run python -m evals validate
```

Manual transcription requires the optional dependency group and suitable
CPU/GPU support. Media downloads additionally require network access and can
create large files.

## Key moments

`find_key_moments` uses the `find-key-moments` spec with no tools, handoffs,
repository access, skills, playbooks, or model override. It receives versioned
JSON source metadata and ordered timestamped segments inside the existing
`{"input": "..."}` request. `Assistant.from_name(..., output_type=KeyMomentsOutput)`
and `domain.runtime.execution.run_sync(..., surface="task")` perform one typed
SDK call. Domain validators reject malformed input, missing structured output,
and unknown/reversed IDs, and sort valid moments chronologically. Timestamps
and excerpts are resolved by VOD against its own stored source, never by a model.

The task service has an explicit two-task catalogue with labels, versions,
timestamp prerequisites, and output kinds. Both definitions start at version 1;
increment the version when changing prompts, input assembly, or output contracts.
Both HTTP task inputs are limited to 64,000 estimated `o200k_base` tokens and
10 MiB of UTF-8 bytes before execution. They never silently truncate source.
Configurable provider context errors are task failures. Distillation's existing
prompt, wrapper, Markdown result, and single-call behavior are unchanged.

`tests/test_key_moments.py` exercises the real task route through a stubbed SDK.
`evals/datasets/find-key-moments.json` separately defines seven synthetic prompt
fidelity cases. Assistant-only evaluation does not test the task's `output_type`.
No paid model evaluations or hosted dataset mutations are part of offline checks.
