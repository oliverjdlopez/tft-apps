# Transcription batching experiment

See [commands and measurement limits](../../../docs/transcription-benchmark.md).

From the suite root:

```bash
vod-review/.venv/bin/python dev/benchmark/transcription/benchmark.py /absolute/path/audio.m4a
```

Runs the unbatched baseline, batch 4, and batch 8 sequentially on CUDA with
large-v3, FP16, beam 5, VAD, and segment timestamps. Requires the existing VOD
transcription environment and cached model weights. Results default to ignored
`results/` beside this script. No application services or databases are used.
