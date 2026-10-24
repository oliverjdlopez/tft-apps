# Transcription batching benchmark

The standalone runner in `dev/benchmark/transcription/benchmark.py` compares
the current VOD recognition baseline with faster-whisper's batched pipeline at
batch sizes 4 and 8. It does not change application transcription settings,
publish transcripts, download source media, or access application databases.

## Run

Use the VOD Python environment with its optional `transcription` dependency
installed (`uv sync --extra transcription` from `vod-review/` if needed).
From the suite root:

```bash
vod-review/.venv/bin/python dev/benchmark/transcription/benchmark.py \
  /absolute/path/speech-heavy.m4a /absolute/path/noisy-gameplay.m4a \
  --repeats 3
```

The default is `large-v3`, CUDA device 0, FP16, beam 5, VAD enabled,
and segment timestamp generation. These are explicit benchmark settings;
application dotenv overrides are not loaded. Model weights must already be
cached; pass `--allow-download` to permit a missing model download, or
`--model /absolute/path/ctranslate2-model` for a local model directory.
Model download time, if permitted, is included in model loading time.
Use `--language en` to fix English for all trials, or omit it to match the
application's language autodetection. `--device-index` selects a CUDA device.
There is no CPU fallback. Avoid concurrent GPU jobs for comparable measurements.

Each source runs baseline, batch 4, and batch 8 in separate fresh processes.
Repeats rotate their order. Each completion is printed before the next starts.
Failures, including out-of-memory errors, are recorded and subsequent trials
continue; any failed trial produces a nonzero final exit code. Interrupting the
runner retains already written artifacts but may leave the current trial incomplete.

## Artifacts and interpretation

Default output is a unique ignored directory under
`dev/benchmark/transcription/results/`. `--output /path/to/new-directory` chooses
another destination, which must not exist; keep custom result directories ignored.
Every trial saves configuration, a worker log, measurements, plain transcript,
and JSON segments with original-media start/end seconds. The run saves
`results.json` incrementally and `summary.json` with per-source medians and
speedup against the unbatched baseline. Failed trials are excluded from medians;
successful trial counts make incomplete comparisons visible.

Measurements include:

- Model construction/loading time, separately from transcription.
- Total transcription time, including preparation and fully consuming the lazy
  segment iterator. This is the primary speed comparison.
- Time before `transcribe()` returns and subsequent segment iteration time.
  These are API boundaries, **not** pure CPU preprocessing versus GPU inference:
  preparation and inference can occur on either side depending on the pipeline.
- Audio minutes per wall-clock minute (audio duration / transcription duration),
  source duration, post-VAD duration, segment count, and detected language.
- Sampled peak process VRAM in MiB, queried through `nvidia-smi` approximately
  every 0.5 seconds across loading and recognition. Missing support produces
  `null`; sampling may miss short peaks, especially on WSL drivers.
- Effective transcription/VAD options, dependency versions, source path/size/mtime,
  and whole worker wall time including imports, output writing, and sampling cleanup.

No warmup is performed: each trial includes first-inference overhead, matching a
fresh model per transcription. Repeats reduce noise but are not a steady-state
resident-model benchmark. Source download time is outside the experiment.

The batched pipeline changes chunking, context handling, and fallback behavior;
this is a pipeline comparison, not a guarantee of identical decoding. Explicit
`without_timestamps=False` retains timestamp token generation because the batched
API otherwise defaults to disabling it. Other pipeline defaults remain intact
and are recorded. Consult the installed faster-whisper version's implementation:
[upstream source](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py).

Review saved transcripts for TFT names, dropped/repeated speech, and start/end
alignment near silence and chunk boundaries before choosing a default. No
automated accuracy score or timestamp correctness claim is produced. Keep test
audio and generated artifacts out of Git.

## Offline validation

From `vod-review/`:

```bash
.venv/bin/python -m unittest discover -s ../dev/benchmark/transcription -p 'test_*.py'
```

These checks simulate lazy recognition to verify timing, requested options,
timestamp retention, and failure recording. They do not exercise CUDA, model
downloads, recognition quality, or real batching throughput.

## Local GPU run: 2026-10-23

Extracted the middle 30 minutes of `~/tftaud.mp4` (28,090.027 seconds total),
starting at 13,145.013 seconds, into ignored
`dev/benchmark/transcription/test_aud.mp4`. FFmpeg copied the AAC stream without
re-encoding; the resulting duration is 1,800.011 seconds due to packet boundaries.
The source file was preserved. Command from the suite root:

```bash
vod-review/.venv/bin/python dev/benchmark/transcription/benchmark.py \
  dev/benchmark/transcription/test_aud.mp4 --repeats 3
```

All nine trials succeeded on an RTX 4070 (12 GB), using faster-whisper 1.2.1.
Artifacts are in the ignored local directory
`dev/benchmark/transcription/results/20261023T155511.073533Z/`.

| Pipeline | Trial times (seconds) | Median | Speedup |
| --- | --- | --- | --- |
| Unbatched | 120.9, 90.7, 88.8 | 90.7 s | 1.00x |
| Batch 4 | 30.3, 29.6, 30.2 | 30.2 s | 3.01x |
| Batch 8 | 26.9, 24.9, 24.5 | 24.9 s | 3.64x |

Times exclude model loading. Approximately 5.9 GB of device memory was occupied
before testing; per-process memory reporting was unavailable. These are pipeline
speed measurements, not verified quality-equivalent results: default VAD retained
993.872 seconds unbatched versus 922.544 seconds batched. The unbatched minimum
silence duration was 2,000 ms versus 160 ms batched, with a 30-second maximum
speech segment in the batched path. First-repeat transcripts contained 2,563,
2,334, and 2,366 whitespace-delimited words respectively; word counts do not
establish accuracy. Listening checks and timestamp alignment remain unverified.
Compare matched VAD settings and inspect omitted/repeated passages before
changing application defaults.
