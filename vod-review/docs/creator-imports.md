# Automatic creator imports

Open **Automatic imports** in the VOD Review or Wisps header. Enter one YouTube
channel or Twitch creator URL per line, a daily time, an IANA timezone such as
`America/New_York`, and a lookback window in hours or days. Existing browser-local
replay sources seed the form when no schedule has been saved. Choose video quality,
enable daily imports, and save. The saved schedule is backend state shared by both
views; the manual **Source settings** list remains browser-local.

Saving sets the next daily time without starting a download. **Run now** saves the
form first and starts a scan immediately, including while daily imports are off.
It uses the current instant as the end of its window. Daily runs use the scheduled
instant as the end: a 48-hour window at Wednesday 09:00 covers Monday 09:00 through
Wednesday 09:00. Publication boundaries are inclusive; overlapping windows do not
download the same media twice.

Keep the desktop/backend running and the machine awake. The backend checks due
times every 15 seconds. After downtime it runs the most recent missed daily slot
once, rather than replaying every missed day. It does not expand the lookback to
cover the whole downtime. Settings and run history survive shutdown. Turning off
daily imports prevents future runs; a run already in progress finishes using its
saved settings. Only one automated scan/download batch runs at a time. Manual
uploads, downloads, and viewing remain available.

Timezone rules follow the host IANA timezone database. A repeated daylight-saving
time runs once, at its first occurrence. A nonexistent time shifts forward by the
daylight-saving gap (02:30 becomes 03:30 during a one-hour spring gap).

## Discovery and import behavior

YouTube scans uploads, completed streams, and shorts separately; Twitch scans
creator archives newest first. Active/upcoming streams are skipped. Scheduled
discovery fully extracts metadata and reads lazily until the publication window
ends; it does not use the manual replay preview's 12-entry limit. This relies on
the platforms' newest-first feed order. An absent YouTube tab is an empty feed.
An unavailable creator, an extractor error, or a download failure is recorded in
the activity panel while other creators and media continue.

Only precise `timestamp` or `release_timestamp` metadata establishes an hourly
publication window. Missing timestamps, including metadata containing only an
upload date, are skipped with a visible error rather than assigned an invented
publication time. Extractor reads have a 90-second inactivity timeout and each
network request a 30-second socket timeout. Successful entries from a partially
failed feed remain eligible. Discovery runs
[yt-dlp](https://github.com/yt-dlp/yt-dlp#usage-and-options) with metadata-only,
lazy, full extraction; media transfer starts through the application's ordinary
URL-import task afterward.

Downloads are serial within a batch, use the selected quality and native FPS,
and fetch the full video. They reuse the same persistence, video validation,
optional configured app-local media cache, download progress, and playback
preparation as a manual URL upload. Each imported VOD appears in the existing
library, which refreshes every 15 seconds and when the view regains focus.
Round/Wisp inference, annotation, transcription, and Google Drive clip uploads
remain explicit user actions. Draw a crop and process the imported video as usual.

Provider media IDs prevent duplicate automatic imports across creators, URL
aliases and overlapping windows. Existing full video URL downloads in the
library or in progress are also skipped; partial clips and audio-only downloads
do not count as full video imports. Failed imports can retry when discovered by
a later run. Deleting an imported video permits importing it again. Interrupted
runs are marked during restart; completed downloads are recovered even when
shutdown occurred before automation recorded their association.

## Ownership and API

`backend/replay_automation/` owns validation, timezone calculations, metadata
discovery, SQLite claims, and scheduling. `backend/app.py` starts one owner in the
FastAPI lifespan and awaits its shutdown before stopping ordinary download tasks.
The same runtime serves the two persistent desktop video views.

- `GET /api/replay-automation`: saved settings, next time, ten recent runs, and
  the hundred most recent imported media associations with download progress.
- `PUT /api/replay-automation`: validate and save `enabled`, `sources`,
  `daily_time` (`HH:MM`), `timezone`, `window_hours` (greater than zero, up to 90
  days), and `quality` (`480p`, `720p`, `1080p`, or `best`). Up to 25 unique
  creator URLs are accepted. Unknown fields are rejected.
- `POST /api/replay-automation/run`: start an explicit run; concurrent runs return
  409 and an empty creator list returns 400.

The schedule, run records and provider-ID associations live in `replay_schedule`,
`replay_runs`, and `replay_imports` in the existing ignored
`VOD_DATA_DIR/vod.sqlite3`. Ordinary tasks remain in `download_tasks` and videos
in `videos`. This creates no external service, credential store, shared package,
or separate desktop process. Like the rest of the app, the scheduler assumes one
owned VOD backend; do not run multiple backend processes against the same state.

## Offline validation

From the VOD application root:

```bash
.venv/bin/python -m pytest backend/tests/test_replay_automation.py backend/tests/test_api.py -q
```

From `frontend/`:

```bash
npm test
npm run build
```

Tests use temporary SQLite state, fake creator metadata streams, and stubbed
transfers. They cover DST, missed runs, concurrency, duplicate/manual imports,
retries, interrupted runs, the normal playback path, publication boundaries,
feed coverage, settings validation, progress polling, and unsaved form edits.
They do not contact Twitch/YouTube, download real media, or run inference.
