# Shared media across independent applications

In `tft-apps`, both backends now default to the suite-owned `media/` catalogue.
Desktop launches enforce that shared coordinate. Both expose publication,
discovery, and verified content by `tft-resource:<id>`; VOD can publish an
existing review or import a reference as a separate review. See the current
[suite media sharing guide](../../docs/shared-media.md) for APIs and examples.
The reuse rules below still apply. An explicitly empty `TFT_MEDIA_DIR` disables
sharing; leaving it unset in this suite selects the default shared directory.

ChatTFT and VOD Review use the same media catalogue and disk directory while
keeping application databases and installed environments independent.

## Setup

On the same Linux/macOS host, both suite applications default to `<suite>/media`.
For standalone processes, an optional override must match in **both** environments:

```bash
export TFT_MEDIA_DIR=/absolute/path/to/shared-tft-media
```

The directory is created automatically and contains `catalog.sqlite3`, immutable
`media/` files, `locks/`, and resumable/transient `work/`. Both processes must have
read/write access. Use a local disk, or a bind-mounted local volume shared by
containers on the same host. Do not place the SQLite database or advisory locks
on NFS, cloud-synced folders, or independent disks on different servers.

URL reuse requires system `ffmpeg` **and** `ffprobe` on PATH. It currently
uses POSIX file locks. Existing local mode remains available with an explicitly
empty `TFT_MEDIA_DIR`. The setting is read when a download is requested;
this media integration does not use the app RDS loader.

Start each application with its existing command. No new server, Python package
dependency or database credentials are needed.

## Reuse rules

| Available media | Request | Behavior |
| --- | --- | --- |
| Full video with audio | Transcription of that video | Return the existing file directly |
| Audio only | VOD review | Download video and keep both representations |
| Compatible video | Same source/range/quality | Reuse its path with a new independent review record |
| Longer compatible media | Contained time range | Cut a local derivative; timestamps begin at zero |
| Higher-resolution video | Lower capped resolution | Convert locally to the requested cap |
| Short clip or lower quality | Full video or higher quality | Download the missing representation |
| Download in another process | Same source | Wait for its source lock, then check the catalog again |
| Missing or size-changed cache file | Same request | Download again instead of trusting a stale archive |

YouTube URL aliases normalize to the video ID; Twitch VOD and clip aliases
normalize similarly. URL seek query parameters are not time-range requests.
Use each application's explicit range controls. Channel URLs are rejected in
shared mode because their content identity changes over time.

The catalog records actual audio/video streams, dimensions, duration, source
timeline coverage, and the selection profile. A request for `best` is satisfied
only by that recorded profile. Numeric VOD quality caps can reuse an equal or
higher resolution, with local conversion as needed. Custom ChatTFT format
selectors require the same selection profile. Ordinary transcription accepts
any cached representation with audio and sufficient coverage.

Downloads retain the existing yt-dlp implementations. A per-source OS lock
spans lookup, download, and atomic publication; SQLite transactions stay short.
An interrupted process releases its lock automatically. Failed or paused
downloads are never cataloged as complete. VOD checkpoint/pause/resume remains
local to its existing task, and ChatTFT isolates resumable work and archives by
source, format, and range. Partial VOD checkpoints become shared only after
the requested download completes.

## Existing files

Old downloads are not automatically inferred from filenames: their URL,
coverage, and quality may be unknown. Register a known local file without
downloading it again:

```bash
uv run python -m backend.media_store /absolute/path/to/video.mp4 --url https://youtu.be/VIDEO_ID --kind video --profile video:720p
```

In ChatTFT the equivalent module is `scripts.transcription.media_store`. For audio use
`--kind audio --profile audio`. For a clip from source seconds 600–900, add
`--start 600 --end 900`. Omit `--end` only when the file reaches the end of the
source. Record the original quality selection accurately; do not label an
arbitrary low-quality file `video:best`.

Registration copies the source into catalog-owned storage (or returns an
existing matching entry) and leaves the original untouched. Subsequent URL
requests in either application use the shared entry.

## Ownership and cleanup

VOD review IDs, boxes, jobs, annotations, and playback derivatives remain in
its own database/directories. A persistent `videos.shared_media` flag prevents
the delete endpoint from unlinking a shared source, even if shared mode is
later disabled. Local uploads retain their existing deletion behavior.

Shared assets are retained indefinitely; there is no automatic eviction.
Deleting a review removes that review's state, not the shared source. Do not
manually remove files still referenced by a review or active transcription.
`--overwrite` in ChatTFT publishes a new asset without replacing files already
in use. Back up the catalog together with its media directory. Work/checkpoint
cleanup should only be done while both apps are stopped.

## Code ownership and validation

The small standard-library catalog package is vendored identically at
`scripts/transcription/media_store/` in ChatTFT and `backend/media_store/` in
VOD Review. This avoids either repository depending on the other application's
package or import paths. The two copies implement catalog protocol v1; keep
them synchronized when changing the protocol, and increment/migrate the
schema version for incompatible changes. Unsupported catalog versions fail
explicitly rather than silently changing another app's schema.

Offline tests generate tiny local videos and exercise reuse, range/quality
matching, process concurrency, missing-file recovery, and immutable refresh:

```bash
uv run pytest -q backend/tests/test_shared_media.py backend/tests/test_shared_video_integration.py backend/tests/test_api.py
```

VOD Review's corresponding tests are `backend/tests/test_shared_media.py` and
`backend/tests/test_shared_video_integration.py`, alongside `test_api.py`.
