# Automatic creator imports

Open **Source settings** or **Automatic imports** in the VOD Review header. Both
open the same **Sources and automation** panel. Enter one YouTube
channel or Twitch creator URL per line, a daily time, an IANA timezone such as
`America/New_York`, and a lookback window in hours or days. Existing browser-local
replay sources seed the form when no creator list has been saved. Choose video quality,
online streaming or offline downloads, video or audio-only media, optional speech
transcription, and a checkpoint interval for resumable offline downloads. Enable daily
discovery and save. The creator list and schedule are backend state shared
by manual replay discovery and automatic imports.

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

Imports are serial within a batch. Offline video downloads use the selected quality,
native FPS, full source, standard validation and playback preparation; an optional
checkpoint interval enables pause/resume recovery. Online mode creates a source-backed
library review without downloading video bytes. Audio-only mode downloads audio
through the ordinary tracked URL-import path. Offline video imports appear in the
library, while audio imports and their transcripts are available in shared Media.
With automatic transcription enabled, video speech is recognized from the saved file;
audio speech is recognized during the audio download. The activity panel reports
download and recognition state, including errors. Select an imported video in the library to read its saved transcript;
queued/running recognition is refreshed automatically. Raw text and detected
language persist in the ordinary transcription tables and publish to shared Media
using the existing transcript-sharing path.

Automatic transcription uses the same optional faster-whisper dependency and
`VOD_WHISPER_MODEL`, `VOD_WHISPER_DEVICE`, and `VOD_WHISPER_COMPUTE_TYPE` settings as
manual transcription. Suite setup includes the dependency; standalone installs
need `uv sync --extra transcription`. Defaults are `large-v3`, CUDA, and float16.
CPU hosts can set `VOD_WHISPER_DEVICE=cpu` and `VOD_WHISPER_COMPUTE_TYPE=int8`.
Missing dependencies, unavailable recognition hardware, and videos without audio
are recorded as transcription failures while the downloaded video remains usable.

Round inference and Google Drive clip uploads remain explicit user actions.
Draw a crop and process the imported video as usual.

Provider media IDs prevent duplicate automatic imports across creators, URL
aliases and overlapping windows. Existing full video URL downloads in the
library or in progress are also skipped; partial clips and audio-only downloads
do not count as full video imports. Failed imports can retry when discovered by
a later run. Failed/interrupted transcriptions also retry when the VOD appears
in a later scan, without downloading again. Enabling transcription after earlier
download-only runs transcribes those videos if they are still within the scan
window. Existing full manual URL imports are eligible too. Completed transcripts
and active manual recognition tasks are reused. Videos outside the lookback
window can still be transcribed manually. Deleting an imported video permits
importing it again. Interrupted runs and recognition tasks are marked
interrupted/failed during restart; completed downloads are recovered even when
shutdown occurred before automation recorded their association.

## Ownership and API

`backend/replay_automation/` owns validation, timezone calculations, metadata
discovery, SQLite claims, and scheduling. `backend/app.py` starts one owner in the
FastAPI lifespan and awaits its shutdown before stopping ordinary download tasks.
The same runtime serves the persistent desktop VOD Review view.

- `GET /api/replay-automation`: saved settings, next time, ten recent runs, and
  the hundred most recent imported media associations with download progress and
  transcription status/errors. Each run includes a `transcribed` count of ready
  transcripts, including reused results.
  `configured` distinguishes saved settings (including a deliberately empty creator
  list) from a new installation that can seed legacy browser-local sources.
- `PUT /api/replay-automation`: validate and save `enabled`, `sources`,
  `daily_time` (`HH:MM`), `timezone`, `window_hours` (greater than zero, up to 90
  days), `quality` (`480p`, `720p`, `1080p`, or `best`), `transcribe` (boolean,
  default false), `mode` (`offline` or `online`, default `offline`), `media_type`
  (`video` or `audio`, default `video`), and `checkpoint_interval_seconds` (null
  or 60–21600, default null). Online mode supports source-backed video reviews
  and cannot be combined with audio, transcription, or checkpoints. Up to 25 unique
  creator URLs are accepted. Unknown fields are rejected.
- `POST /api/replay-automation/run`: start an explicit run; concurrent runs return
  409 and an empty creator list returns 400.

The schedule, run records and provider-ID associations live in `replay_schedule`,
`replay_runs`, and `replay_imports` in the existing ignored
`VOD_DATA_DIR/vod.sqlite3`. Ordinary tasks remain in `download_tasks` and videos
in `videos`; recognition remains in `transcription_tasks`, linked by
`replay_imports.transcription_task_id`. Existing databases migrate in place and
older schedules retain download-only behavior until transcription is enabled.
`GET /api/videos/{video_id}/transcription` retrieves the latest saved recognition.
This creates no external service, credential store, shared package,
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
feed coverage, settings validation, progress polling, unsaved form edits, transcription retries without another
transfer, reuse of manual/completed recognition, transcript retrieval, and schema
migration.
They do not contact Twitch/YouTube, download real media, or run inference.
