# Media sharing between backends

ChatTFT and VOD Review use the suite's ignored `media/` directory and its
`catalog.sqlite3`. Both backends can publish, discover, and retrieve immutable
files by `tft-resource:<id>`. Review IDs, analysis jobs, playback
derivatives, and original transcript records remain owned by their application.
VOD publishes immutable snapshots of completed transcript text and available
segment timestamps for sharing.

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
as complete. Completed VOD transcripts are published as text resources;
new recognition also publishes a linked JSON resource containing segment timing.
ChatTFT CLI transcript outputs still require explicit publication.
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

Existing VOD imports still appear in its ordinary library. The desktop also
provides a shared media browser; assistant tools remain outside this integration.

## Desktop media browser

Open **Media** in the desktop navigation or press Ctrl/Cmd+9. The library lists
all published resource kinds: `video`, `audio`, `image`, `text`, and `data`, newest
first. Search loaded entries by name, source or reference, and filter by type.
**Load more** retrieves additional catalogue pages; **Refresh** reloads the
library. Selection and filters remain when switching tabs.

Select a resource to see its name, source, kind, format, byte size and portable
`tft-resource:ID`. Text previews also show the token count for the original
decoded source text using OpenAI's `o200k_base` encoding. This counts the text
only; it excludes chat message framing and may differ from a model that uses
another tokenizer. Structured JSON may be pretty-printed for preview, while its
token count remains based on the stored source. If the count cannot be produced,
the text preview remains available and the details show that token counting is
unavailable, such as when ChatTFT cannot load the tokenizer assets. **Copy
reference** copies that identifier for use in either
backend's API or CLI; the selectable reference remains available even when a
preview fails or its format is unsupported.

Text and recognized textual data retain the transcript reader, with formatted
JSON and a 10 MB read limit. Images display inline; audio and video use native
playback controls and verified HTTP content with range support. Playback pauses
when leaving the tab. Binary data and unsupported formats remain browseable and
referenceable without decoding them as text. Empty libraries, unavailable
storage, missing files and integrity failures have recoverable status messages.
The local shell is the only renderer permitted to request catalogue operations
or copy references, through the desktop-owned ChatTFT backend.

For a loaded, nonempty text/transcript or recognized textual data resource,
**Distill transcript** runs the `distill-transcript` assistant. Its output appears
in **Distilled reference** above the original source, preserving the returned
Markdown as selectable text. Loading and error messages accompany the action;
**Retry distillation** retries a failed request, and **Distill again** explicitly
requests a fresh result. A failed rerun keeps the previous successful output.
Binary resources and empty or unreadable text cannot start distillation.

The desktop main process accepts only a portable resource reference. It rereads
verified source bytes and display metadata from the owned catalogue, then posts
them to `/api/assistants/tasks/transcription_pipeline/run`. That task invokes only
`distill-transcript`, using ChatTFT's configured model and credentials. The normal
10 MB text-read cap applies; model context limits may be lower. Responses have a
ten-minute client timeout; losing the connection does not cancel a model run
already executing in the backend. Model calls occur only after an explicit click.

Running requests and results stay associated with their source reference when
the user selects other resources or switches tabs. A pending request disables
another run for the same source. Results remain in the current desktop window
until its shell reloads or closes; they are not published to the shared catalogue
or automatically ingested into ChatTFT context. Both source and assistant text
are displayed without executing embedded HTML. Hosted pages cannot invoke the
distillation IPC action. VOD Review's frontend and backend are unchanged.

VOD automatically publishes completed recognition as UTF-8 `text` resources,
named after the source video when available, with task/video/language metadata.
New recognition additionally publishes a `.json` companion as kind `data`,
with MIME type `application/json` and metadata type `timestamped_transcript`.
Both resources share the catalogue source `vod-review:transcription:<task_id>`.
The JSON and its metadata include `text_reference` linking to the text resource.
Find it through either backend's shared-media API or desktop **Media → Data**.

The JSON contract has `schema_version: 1`, `transcription_task_id`, `video_id`,
`language`, `text_reference`, `transcript`, `time_unit: "seconds"`,
`time_origin: "media_start"`, and an ordered `segments` array. Each segment
contains `start`, `end`, and `text`. These are Whisper speech-segment timestamps
relative to the transcribed file; for a downloaded clip, zero means the clip's
start. Word-level timing is not enabled. VOD Review's transcript modal and
task API retain their existing plain-text payload.

Backend startup also publishes older completed transcripts from its own SQLite
database, so no download or transcription rerun is needed. Recovery reuses a
verified snapshot when its contents match and restores missing shared files from
the local result. New tasks persist timing alongside text before publication,
allowing a failed JSON publication to retry after restart. Older text-only tasks
have no timestamps to recover and continue publishing only text; no recognition
is rerun automatically. Catalogue failures leave the completed local transcript intact
and log a warning; the next startup retries sharing. An explicitly empty
`TFT_MEDIA_DIR` disables publication. Refresh the Media library after completion.

ChatTFT CLI transcript output files still require explicit publication. Add a
completed file without remote I/O, from `tft-chat/`:

```bash
.venv/bin/python -m scripts.transcription.media_store.resource_cli publish /absolute/path/transcript.txt \
  --kind text --source youtube:VIDEO_ID --content-type text/plain
```

VOD uses `backend.media_store.resource_cli` with the same arguments. Publishing
preserves the original and creates an immutable catalogue snapshot. The desktop
browser leaves catalogue content unchanged and does not run downloads or speech
recognition; text distillation returns a separate result in the reader.

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

From `desktop/`, run `npm test`. The media reader and shell IPC have
offline Node coverage; `tests/workspace-electron.mjs` also exercises real
media selection, references, filtering, retained state and failure/retry using a local
HTTP catalogue fixture. It also covers explicit distillation, safe output display,
duplicate prevention, per-source result isolation and retry with a fixture task
endpoint. The ChatTFT task HTTP test reaches the real assistant preparation path
with the model call stubbed. From `tft-chat/`:

```bash
.venv/bin/python -m pytest tests/test_task_service.py tests/test_shared_resources.py tests/test_shared_transcription.py \
  tests/test_transcription_download_vod.py ../desktop/tests/test_shared_media_exchange.py -q
```

From `vod-review/`:

```bash
.venv/bin/python -m pytest backend/tests/test_shared_resources_api.py \
  backend/tests/test_shared_media.py backend/tests/test_shared_video_integration.py \
  backend/tests/test_shared_transcripts.py -q
```

Transcript tests exercise the real VOD completion path with recognition stubbed,
then discover and read the exact UTF-8 bytes and JSON segment timestamps through
the actual ChatTFT API. They also cover local schema migration, timed-silence
results, publication failure/recovery, and immutable timing changes.

Cross-backend tests invoke each application's own interpreter and actual HTTP
routes with temporary state, synthesize a small local video, stub network
downloads, and omit application lifespans. They do not call models, contact
YouTube/Twitch, run GPU inference, or initialize application RDS databases.

## Local audio uploads

VOD Review's **Upload** inspects actual streams. Video enters the normal library;
audio-only files, including MP4 and audio with cover art, prompt for confirmation.
Cancel removes the pending upload. Confirm starts transcription with progress,
retry, and **View transcript** independent of the selected video. Completed text
and timestamped JSON use the existing shared publication path. Audio creates no
video review record and requires the usual faster-whisper/device configuration.

`POST /api/uploads` returns `{kind: "video", video: ...}` or
`{kind: "audio", upload_id: ..., name: ...}`. Audio is retained under
`data/audio-uploads/`. `POST /api/uploads/{upload_id}/transcription` confirms
recognition, reusing active/completed tasks. `DELETE /api/uploads/{upload_id}`
removes unconfirmed input; confirmed input remains for retries. Closing the page
before answering may leave pending bytes on disk, but never starts recognition.
Progress is displayed for the current page session; completed transcripts remain
available in desktop Media after reload.

## Watch & Read

**Watch & Read** (Ctrl/Cmd+6) is a separate desktop destination for viewing
existing content. It opens `/watch` on the owned VOD frontend, in a persistent
sandboxed view, sharing VOD's frontend/backend processes. The VOD Review page
and Media browser retain their existing behavior.

The left library shows videos with a completed transcript, completed round
results, or both. It joins shared catalogue videos and transcript snapshots with
existing VOD records, including online reviews that have no downloaded file.
Audio-only transcripts, unrelated resources, unprocessed videos, and unfinished
results are excluded. An older successful result remains available while a newer
attempt runs or fails. Search filters the list; Refresh rereads saved state.

Each entry shows available artifacts. **Video** includes the existing local or
YouTube/Twitch player and, when present, game and round navigation. Round clicks
seek actual saved frame timestamps. The existing VOD game-grouping function is
reused. **Transcript** fills the available main viewing area and provides the
source transcript, language, and, when
available, searchable speech segments whose timestamps open the video at that
position. Legacy transcripts remain plain text. Changing reader modes retains
the playback position, and leaving the desktop tab pauses playback. Selection
and search survive desktop tab switches.

The GET-only `/api/viewing-library` and `/api/viewing-library/{identity}` routes
compose existing records without publishing snapshots or starting jobs. Owned
video IDs and explicit `video_id` / `video_reference` metadata link artifacts;
catalogue-only source joins require matching start/end coverage. No filename
matching is used to associate a transcript with a video. All catalogue pages
are considered. Stored round results remain VOD-owned; they are not copied into
a new catalogue protocol.

`/api/viewing-library/{identity}/content` serves an existing local copy with
range support without changing VOD Review's saved playback mode. Existing HLS
assets are used when available in Offline review mode; otherwise the original
file is played directly. Viewing never starts playback conversion. Unsupported
codecs, missing files, unavailable embeds, and unreadable transcript snapshots
have explicit messages; a playback failure does not prevent transcript reading.
Sharing disabled/unavailable is reported separately from an empty library.
This page offers no discovery, import, analysis, recognition, or distillation.

Offline coverage: `backend/tests/test_viewing_library.py` exercises the real
HTTP routes with temporary SQLite/catalogue state and no application lifespan;
`src/ViewingLibrary.test.tsx` covers reading, seeking, filtering, stale responses,
pause-on-hide, and recovery. Desktop workspace tests cover separate persistent
views and shared service readiness. Live provider playback requires separate
network verification.
