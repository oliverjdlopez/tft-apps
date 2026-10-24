"""Download and decode five minutes of Twitch audio on a temporary SDK worker."""

import asyncio
import json
import os
from pathlib import Path
import uuid

import runpod

APP_ROOT = Path(__file__).resolve().parents[1]
if runpod.is_local():
    from dotenv import load_dotenv

    load_dotenv(APP_ROOT / ".env", override=False)
    runpod.api_key = os.environ["RUNPOD_API_KEY"]

suffix = os.environ.get("VOD_DOWNLOAD_PROBE_SUFFIX") or uuid.uuid4().hex[:12]
app = runpod.App(f"vod-download-probe-{suffix}")

if runpod.is_local():
    remote_download = app.queue(
        name="twitch-audio-probe", cpu="cpu3c-2-4", workers=(0, 1),
        idle_timeout=5, execution_timeout_ms=900_000,
        dependencies=["yt-dlp==2026.08.19"], system_dependencies=["ffmpeg"],
        env={"VOD_DOWNLOAD_PROBE_SUFFIX": suffix},
    )
else:
    def remote_download(function):
        """Keep the function plain when the lightweight runtime imports it."""
        return function


@remote_download
def download_probe(url: str) -> dict:
    """Fetch only the first five minutes and verify playable audio remotely.

    Args:
        url: Public Twitch VOD URL to resolve with yt-dlp on the worker.

    Returns:
        Download size, duration, checksum, decoder validation, and runtime tools.
    """
    import hashlib
    import subprocess
    import sys
    import tempfile
    import time
    from pathlib import Path
    import json
    import yt_dlp.version

    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="twitch-audio-probe-") as directory:
        command = [
            sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
            "--format", "bestaudio", "--download-sections", "*0-300",
            "--quiet", "--no-warnings", "--no-simulate",
            "--print", "after_move:%(filepath)s",
            "--output", str(Path(directory) / "audio.%(ext)s"), "--", url,
        ]
        download = subprocess.run(command, capture_output=True, text=True, timeout=600)
        if download.returncode:
            raise RuntimeError(f"Remote Twitch download failed: {download.stderr[-3000:]}")
        audio = Path(download.stdout.strip().splitlines()[-1])
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(audio)],
            capture_output=True, text=True, timeout=30, check=True,
        )
        metadata = json.loads(probe.stdout)
        duration = float(metadata["format"]["duration"])
        stream_types = [stream["codec_type"] for stream in metadata["streams"]]
        if not 298 <= duration <= 302 or stream_types != ["audio"]:
            raise RuntimeError(f"Unexpected audio slice: {duration}s; streams={stream_types}")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-xerror", "-i", str(audio), "-f", "null", "-"],
            capture_output=True, text=True, timeout=120, check=True,
        )
        with audio.open("rb") as source:
            checksum = hashlib.file_digest(source, "sha256").hexdigest()
        return {
            "source_url": url, "duration_seconds": duration,
            "audio_bytes": audio.stat().st_size, "stream_types": stream_types,
            "sha256": checksum,
            "full_decode_passed": True, "wall_seconds": time.monotonic() - started,
            "yt_dlp_version": yt_dlp.version.__version__,
        }


async def main() -> None:
    """Own one temporary endpoint and save evidence before automatic teardown."""
    from runpod.apps.dev import DevSession

    output = APP_ROOT / "data/runpod-download-probe" / suffix
    output.mkdir(parents=True, exist_ok=False)
    state = {"app": app.name, "endpoints": {}, "cleaned_up": False}
    state_path = output / "state.json"
    state_path.write_text(json.dumps(state, indent=2))
    os.environ["RUNPOD_DEV_SESSION"] = "1"
    try:
        async with DevSession([app]) as session:
            state["endpoints"] = dict(session._endpoints)
            state_path.write_text(json.dumps(state, indent=2))
            print(f"Temporary endpoint: {state['endpoints']}", flush=True)
            result = await asyncio.wait_for(
                download_probe.remote.aio("https://www.twitch.tv/videos/2907970518"), timeout=1200,
            )
            (output / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        state["cleaned_up"] = True
        state_path.write_text(json.dumps(state, indent=2))
        print(f"Probe passed; temporary endpoint deleted. Evidence: {output}", flush=True)
    except Exception as exc:
        (output / "failure.json").write_text(json.dumps({"type": type(exc).__name__, "error": str(exc)}))
        raise


if __name__ == "__main__":
    asyncio.run(main())
