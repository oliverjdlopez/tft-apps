# Twitch/YouTube transcription

This directory contains a three-stage media transcription workflow:

1. `download_vod.py` downloads Twitch VOD or YouTube audio by default with
   `yt-dlp`, using native `.part` resume files plus a JSON progress checkpoint
   in `data/checkpoints`. Full video downloads are still available with
   `--video`.
2. `transcribe.py` runs `faster-whisper` against the downloaded media with CUDA by
   default and writes transcript outputs to `scripts/transcription/output`.
3. `main.py` provides a CLI that can run either stage independently or both stages
   in sequence.

## Install

```bash
pip install -e ".[transcription]"
```

`yt-dlp` uses `ffmpeg` for muxing/merging formats and partial downloads. The
downloader prefers a system `ffmpeg` on `PATH`, then falls back to the bundled
`imageio-ffmpeg` binary. If the bundled binary crashes in WSL/Linux with
`ffmpeg exited with code -11`, install a system ffmpeg or pass
`--ffmpeg-location /path/to/ffmpeg`. CUDA transcription requires a working NVIDIA
GPU, CUDA runtime, and compatible CTranslate2/faster-whisper installation.

## Usage

Download Twitch audio only:

```bash
python -m scripts.transcription.main download "https://www.twitch.tv/videos/1234567890"
```

Download YouTube audio only:

```bash
python -m scripts.transcription.main download "https://www.youtube.com/watch?v=abc123"
```

Download the full video:

```bash
python -m scripts.transcription.main download "https://www.twitch.tv/videos/1234567890" --video
```

Overwrite an existing download and ignore the archive entry:

```bash
python -m scripts.transcription.main download "https://www.twitch.tv/videos/1234567890" --overwrite
```

Limit the download to the first 30 minutes:

```bash
python -m scripts.transcription.main download "https://www.twitch.tv/videos/1234567890" --max-time 30
```

Use a specific ffmpeg executable:

```bash
python -m scripts.transcription.main download "https://www.twitch.tv/videos/1234567890" --ffmpeg-location /usr/bin/ffmpeg
```

Transcribe an existing local VOD:

```bash
python -m scripts.transcription.main transcribe data/audio/Twitch-1234567890.mp4
```

Download and transcribe in one command:

```bash
python -m scripts.transcription.main all "https://www.twitch.tv/videos/1234567890"
```

YouTube URLs work with `download` and `all` the same way:

```bash
python -m scripts.transcription.main all "https://youtu.be/abc123"
```

In shared mode, downloads and resumable work live under the ignored suite
`media/` directory. With sharing disabled, media/checkpoints remain under
app-local `data/`. Transcript text, JSON, SRT, and segment checkpoint
outputs are written under `scripts/transcription/output/` by default.

The transcription step defaults to `--device cuda --compute-type float16`; override
those flags for CPU testing or non-default GPU deployments.

## Suite media sharing

Downloads reuse the suite-owned shared catalogue by default. Both backends can
publish and read media through `/api/shared-media`; the transcription CLI reuses
compatible VOD audio/video without another transfer. See the
[suite media sharing guide](../../../docs/shared-media.md) for configuration,
resource references, CLI publication, and offline validation.
