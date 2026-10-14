# Online round review

Public prerecorded YouTube links and Twitch VOD links can be opened in **Online** mode. The review
streams through the source platform's embedded player; choosing a detected round seeks the
player on the original video timeline. Metadata and detected rounds stay local.
Live/upcoming broadcasts, playlists, clips, and local uploads use the existing
Offline workflow. Internet access and permission to embed the video are required
for online playback; the source can subsequently become unavailable.

Use **Draw box** to fetch a still at the current player position and draw the
normalized round-indicator crop. The backend fetches the still from the source;
the application never attempts to read pixels from the player iframe.

Twitch playback uses the interactive player with the frontend hostname as its
`parent`. Saved Twitch downloads retain source identity for switching to Online.
Channels and clips do not support online analysis.

## Sparse analysis

The Online scan interval defaults to **10 seconds** and must be at least one
second. Analysis selects a seekable MP4 video representation at the requested
quality, defaulting to at most 720p. The decoder requests byte ranges instead of
saving a full playable video. Each seek still needs nearby compressed frames;
network savings and runtime depend on the source's encoding and request latency.
A server that does not respond to byte-range requests is rejected with an Offline
option rather than silently read from beginning to end.

Twitch analysis selects HLS at the requested resolution and fetches only the
MPEG-TS segment containing each sample, plus at most its successor. Playlist
durations map timestamps onto the VOD timeline, including discontinuities.
One segment is buffered for adjacent samples. Playlists are limited to 4 MiB
and segments to 64 MiB. Encrypted, byte-range, and fragmented-MP4 playlists
require Offline mode. There is no full-VOD fallback.

The first pass classifies coarse samples from the beginning through a final
sample near the end. Differing readable labels identify intervals for a second
pass at **one-second spacing**, including intervening unreadable coarse samples.
The first readable label also receives neighboring samples. Overlapping intervals
are deduplicated. Existing two-of-three round confirmation runs on the resulting
chronological observations, clearing its vote window across unsampled gaps while
retaining the current confirmed label. Unknown observations never invent a round.

Confirmed results become visible during refinement. Source ranges retain a
review-relative timeline: a review beginning at source time 90 seconds seeks
source time 120 seconds for its local 30-second round. Scheduled and actual frame
timestamps are retained separately, as in Offline analysis.

A round that begins and ends between two coarse samples can be missed. Refinement
improves precision around an observed change but cannot ensure complete detection.
Unreadable crops can leave gaps, and lower video resolutions can harm OCR accuracy.
Use Offline analysis at a denser interval when completeness matters.

## Cache and transport boundaries

The cache contains timestamped lossless crop arrays and OCR observations. Its
identity includes platform-qualified source ID, range, representation policy/resolution, crop,
and analysis version. Ordinary retries reuse saved observations; OCR reruns reuse
crops and can finish without source access when all necessary crops exist. New
crops still require internet. Changing the range, crop, or representation creates
a distinct cache. Temporary signed stream URLs and transport headers remain in
backend memory and are never stored in API responses, review records, or caches.

Individual remote operations use 20-second network deadlines. A failed seek can
renew its URL once, then reports a retry/Offline error. Decoding per sample is
limited to 1,800 frames and 20 seconds in addition to transport read timeouts.
There is no automatic full-download fallback.

## Offline conversion

Selecting **Offline** downloads a local playable copy into the same review.
Online playback remains selected until conversion succeeds. Review identity,
crop, round results, and timestamps remain available; failure leaves Online
playback usable with a retry action. Returning to Online keeps the local copy,
so subsequent Offline selection can reuse it. Mode changes are unavailable while
analysis or conversion is active. Transcription, clip exports, Drive uploads, and
publishing playable media require a local copy in Offline mode.

Per-review conversion recovery keeps simultaneous downloads independently
visible. Checkpointed conversions can resume or be dismissed; partial checkpoints
do not replace the review's full timeline. Source ranges are fixed on import,
including an implicit end, so upstream edits do not silently extend a review.

## Validation and benchmarking

For an opt-in native Electron embed smoke, build the VOD frontend, then run from
`desktop/`:

```bash
env -u ELECTRON_RUN_AS_NODE node_modules/electron/dist/electron --disable-gpu tests/online-vod-electron.mjs
```

Set `VOD_TWITCH_ID` to a numeric public Twitch VOD ID to exercise Twitch
playback and round seeking through the same smoke test. The Twitch smoke shows
the VOD view, mutes its player, and sends a native Play click before seeking. Pending seeks are
retained during metadata loading and preroll ads.

This uses an isolated Electron profile and mocked backend with a real public
YouTube embed by default, or the supplied Twitch VOD. It verifies the desktop VOD view, player identity headers,
round-click seeking, and the 10-second default without application databases or
inference. It requires internet access and a working graphical Electron runtime.

Run the focused sampler suite from `vod-review/`:

```bash
uv run pytest backend/tests/test_online.py
```

The transport tests start a loopback HTTP byte-range fixture and exercise real
PyAV seeks, source offsets, and rejection of sequential-only HTTP servers. The
algorithm tests use deterministic classifiers; no live source or paid inference
is needed. Other cases cover coarse changes, multiple refined transitions, game
resets, unknown gaps, isolated OCR errors, cache reuse, and no voting across gaps.

For a live comparison, use isolated runtime data and a short public prerecorded
YouTube segment with a clearly readable indicator. Analyze the same crop online
at 10 seconds and offline at one second; record wall time, detected labels,
transition timestamp differences, and missed rounds. Record transferred bytes
with a network monitor if available; sampled-frame counts alone are not network
measurements. Check embedding and round seeking inside the actual Electron view,
not only a browser. Live transfer savings and embedding availability require this
separate smoke test and are not established by the fixture suite.

YouTube's current extraction requires EJS challenge scripts and a supported
JavaScript runtime. The Python dependency uses yt-dlp's `default` extra so its
matching EJS package is installed together. Resolution enables Deno and Node
(Node 22 or newer); no solver scripts are downloaded at runtime. See the
[official yt-dlp EJS setup guide](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
Remote decoder input uses Python HTTP byte ranges in chunks of at most 256 KiB,
with adjacent-read buffering, so transport does not depend on the FFmpeg build's
HTTPS behavior. Every HTTP read requires a valid partial-content response.

Twitch compatibility validation covered real public VOD metadata and remote
preview decoding, along with deterministic MPEG-TS timeline and API tests. The
native Electron embed loaded and visually sought to the requested timestamp,
but the automated playback-time check stalled in the validation environment;
sustained native playback remains unverified.
