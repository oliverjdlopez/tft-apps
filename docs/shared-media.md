# Media sharing between backends

ChatTFT and VOD Review use the suite's ignored `media/` directory and its
`catalog.sqlite3`. Both backends can publish, discover, and retrieve immutable
files by `tft-resource:<id>`. Review IDs, annotations, analysis jobs, playback
derivatives, and transcript output remain owned by their application.

## Configuration and ownership

Desktop launches set the same absolute `TFT_MEDIA_DIR=<suite>/media` for both
backends, replacing any inherited source-checkout media path. Standalone
backends and the ChatTFT transcription CLI default to that directory too,
independently of the current working directory. An explicit process environment
variable can select another absolute directory for standalone use; both
processes must use the same value. An explicitly empty value disables sharing
and restores local URL downloads; resource HTTP endpoints then return 503.
This setting does not require RDS credentials or a new service. Restart running
backends after changing their process environment.

The directory contains immutable downloaded files under `media/`, resource
snapshots under `resources/`, per-source `locks/`, and resumable `work/`.
The catalogue and files must reside on a local disk accessible to both
processes. URL download reuse requires POSIX locks, `ffmpeg`, and `ffprobe`
(including WSL on Windows). Resource publication and retrieval do not require
those executables. Do not point this suite at an original checkout's runtime
storage or use network/cloud-synced SQLite directories.

The two apps retain independently vendored `media_store/` implementations and
their own installed Python environments. No application imports the other's
code. A regression check verifies that the protocol copies remain identical.

## URL download reuse

VOD's manual and scheduled URL imports and ChatTFT's transcription downloader
check the same catalogue before downloading. YouTube/Twitch URL aliases share
a source identity. A video with audio can satisfy transcription; audio alone
cannot satisfy video review. Compatible longer clips and higher-resolution
videos can produce local derivatives. Missing/incompatible representations are
downloaded through the existing application downloader. Per-source locks
serialize lookup, transfer, and publication across processes.

Completed new downloads also enter the resource index and are discoverable
through either backend. This index links immutable catalogue-owned media
rather than storing a second copy. Failed/paused downloads are not published
as complete. Transcripts and annotations are not automatically published.
`--overwrite` creates fresh immutable media and references while retaining
previous versions. Existing catalogue entries created before this integration
remain reusable for downloads; publish them explicitly to add resource references.

Register a known local download, without remote I/O:

```bash
# From tft-chat/; the original file is preserved.
.venv/bin/python -m scripts.transcription.media_store /absolute/path/video.mp4 \
  --url https://youtu.be/VIDEO_ID --kind video --profile video:720p
```

From `vod-review/`, use `-m backend.media_store` instead. For partial source
coverage, supply `--start` and `--end`; omit `--end` only for a file reaching
the end of its source. The original media reuse contract is described in the
[VOD guide](../vod-review/docs/shared-media.md).

## HTTP publication and access

Both backend origins expose the same routes:

| Route | Behavior |
| --- | --- |
| `POST /api/shared-media?kind=video&source=example&name=clip.mp4` | Publish the raw request body; its `Content-Type` records the MIME type. |
| `GET /api/shared-media` | List resources, newest first; exact `source`, `kind`, and `name` filters, `limit` (1–1000), and `offset` are supported. |
| `GET /api/shared-media/{reference}` | Inspect metadata, SHA-256, provenance, and the content URL. |
| `GET /api/shared-media/{reference}/content` | Download verified bytes; HTTP ranges support playback and partial reads. |

Kinds are `video`, `audio`, `image`, `text`, and `data`. Publications always
receive a new ID. HTTP uploads stream to disk with a 5 GiB limit and clean up
on failure or disconnect. API callers supply bytes and logical identities,
never server filesystem paths. The returned `content_url` is relative and
works at either backend origin. References identify local catalogue entries;
they are not remote URLs or authorization tokens.

For example, publish through VOD and read through ChatTFT:

```bash
curl -X POST --data-binary @clip.mp4 -H 'Content-Type: video/mp4' \
  'http://localhost:8000/api/shared-media?kind=video&source=example&name=clip.mp4'
# Substitute the returned reference and ChatTFT's configured port.
curl 'http://localhost:8300/api/shared-media/tft-resource:ID/content' -o copy.mp4
```

The existing local backend access model applies. Shared content is served as
an attachment with `nosniff`. Unknown references return 404, missing files 410,
integrity failures 409, and disabled/unavailable storage 503.

## VOD library integration

`POST /api/videos/{video_id}/share` publishes a snapshot of an existing uploaded
or downloaded VOD and returns a portable reference. The original review and
its files remain intact. ChatTFT can list and read that snapshot immediately.

`POST /api/videos/shared` with JSON `{"reference":"tft-resource:ID"}` validates
the bytes as a video, creates an independent review pointing at the immutable
shared file, and starts normal playback preparation. This lets VOD consume
video published through ChatTFT without another transfer. Review deletion
removes app-owned state while preserving shared bytes. Shared snapshots are
retained indefinitely; no eviction or delete-resource endpoint is provided.
Back up the catalogue and its files together. Resolve paths as read-only and
pull a copy before editing.

These are backend/API capabilities; there is no new media-browser UI or
assistant tool. Existing VOD imports still appear in its ordinary library.

## Python and CLI access

`ResourceStore` supports `publish`, `find`, `get`, `resolve`, `pull`, `read_text`,
and `read_json`. `resolve` verifies size and SHA-256; `pull` refuses to replace
an existing destination. Text/JSON reads default to 10 MB. The resource schema
is additive and preserves the existing version-one media catalogue.

From `tft-chat/`:

```bash
.venv/bin/python -m scripts.transcription.media_store.resource_cli publish notes.json \
  --kind data --source example --content-type application/json
.venv/bin/python -m scripts.transcription.media_store.resource_cli list --source example
.venv/bin/python -m scripts.transcription.media_store.resource_cli pull tft-resource:ID notes-copy.json
```

VOD uses `backend.media_store.resource_cli` with the same arguments.

## Offline validation

From `desktop/`, run `npm test`. From `tft-chat/`:

```bash
.venv/bin/python -m pytest tests/test_shared_resources.py tests/test_shared_transcription.py \
  tests/test_transcription_download_vod.py ../desktop/tests/test_shared_media_exchange.py -q
```

From `vod-review/`:

```bash
.venv/bin/python -m pytest backend/tests/test_shared_resources_api.py \
  backend/tests/test_shared_media.py backend/tests/test_shared_video_integration.py -q
```

Cross-backend tests invoke each application's own interpreter and actual HTTP
routes with temporary state, synthesize a small local video, stub network
downloads, and omit application lifespans. They do not call models, contact
YouTube/Twitch, run GPU inference, or initialize application RDS databases.
