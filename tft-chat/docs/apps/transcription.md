# Transcription

The repository has two related transcription paths: a media CLI that downloads
and transcribes VODs, and an assistant task that cleans, compacts, and analyzes
existing transcript text.

## Media CLI

`scripts/transcription/main.py` provides `download`, `transcribe`, and `all`
stages through the installed `tft-transcribe-vod` command.

`download_vod.py` uses yt-dlp, resumable `.part` files, archive/checkpoint
state, and unique temporary paths so concurrent runs do not share intermediate
output. It prefers a system ffmpeg executable and falls back to
`imageio-ffmpeg`.

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

`domain.tasks.transcript.run_transcription_pipeline` runs three assistant
stages synchronously:

1. The cleaning assistant returns structured edits.
2. Python applies valid edits to the JSONL transcript.
3. The compacting and analysis assistants produce the final result.

Invalid or non-JSON cleaning output leaves the original transcript unchanged
instead of terminating the pipeline.

## Validation and runtime requirements

```bash
uv run pytest -q tests/test_transcription_download_vod.py tests/test_agent_workflow_evals.py
```

Manual transcription requires the optional dependency group and suitable
CPU/GPU support. Media downloads additionally require network access and can
create large files.
