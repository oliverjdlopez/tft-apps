# Download Twitch audio on a temporary Runpod worker

Run from `vod-review/` with `RUNPOD_API_KEY` in the app-local `.env`:

```bash
UV_CACHE_DIR=/tmp/tft-runpod-uv-cache uv run --no-project \
  --with runpod==2.0.0rc1 --with python-dotenv python scripts/runpod_download_smoke.py
```

The probe creates a temporary CPU Serverless endpoint using the SDK's standard
runtime image. It installs yt-dlp and FFmpeg at startup; no custom image is built.
It downloads the first five minutes of Twitch VOD `2907970518`, checks that the
result contains audio only and lasts roughly 300 seconds, and decodes the entire
slice with FFmpeg. It returns file size, checksum, tool version, and elapsed time.

Evidence is saved under ignored `vod-review/data/runpod-download-probe/<id>/`.
The audio exists only in a temporary worker directory. The SDK development
session deletes its endpoint on exit, including after a job error. If the local
process is killed, inspect `state.json` and delete any remaining endpoint listed
there. An exception during teardown must also be checked for leftover resources.
This probe neither transcribes audio nor changes an existing endpoint.

The Runpod SDK 2 release candidate runs in an isolated `uv` environment and does
not change application dependencies. A successful probe establishes access from
the specific allocated worker at that time; it does not guarantee Twitch access
from every Runpod address or future availability of the VOD.

Verified on 2026-10-24: a CPU worker in US-NC-2 downloaded 5,724,706 bytes of
audio lasting 300.010667 seconds and decoded the complete slice successfully.
The function took 2.24 seconds after SDK dependency setup. The temporary endpoint
was deleted. Evidence: `data/runpod-download-probe/937dca8f6fce/result.json`.
