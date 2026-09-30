# Upload round clips to Google Drive

In the **Analyze** / round-classification workspace, run round classification,
then click **Upload to GDrive** above **Confirmed round changes**. This uploads
one separate MP4 per included parsed round across the entire VOD and every game.
Use **Rounds** to choose all rounds (including hidden ones) or key rounds only.
Key rounds match the existing UI: all of stage 1, the first round of each later stage, plus 3-2 and 4-2. Selection checkboxes and the selected-game filter apply only to
the existing combined video download.

**Start offset (s)** is shared with the player's seek offset. Positive values
start after the detected timestamp; negative values start before it. The allowed
range is −3600 to 3600 seconds. **Duration (s)** sets the length of each clip from
1 to 180 seconds. Defaults remain all rounds, zero offset, and 60 seconds.

Clip start is the classifier's actual frame timestamp plus the offset, clamped
to zero. Rounds shifted past the source end are skipped. Clips may overlap and
continue into the next round; the source end shortens a clip when necessary.
The server validates settings and derives clips from stored classification
results. Video is re-encoded with H.264 and optional AAC audio.

Settings are fixed when a batch starts and its controls are disabled while it
runs. The batch's settings appear beside its progress. Retrying with the same
settings resumes that batch; changing settings after completion or failure
creates a new folder and batch. Changing settings does not modify existing
Drive files. After reloading the page, choose the same settings to retry an
existing failed batch. The API accepts `key_rounds_only`, `offset_seconds`, and
`duration_seconds` in the upload POST's JSON body; omitted fields use defaults.

The upload button requires completed round-classification results for the selected
video. Connecting Google alone does not generate round timestamps. If uploading
is disabled, the page explains whether to process the video, wait for its first
classification, or retry a classification that detected no rounds. Existing
completed results remain uploadable while a new analysis runs. Returning to the
tab refreshes video results and the saved Google connection status. The page shows
**Google Drive connected** after authorization; this reports a saved grant, whose
validity is checked when uploading.

## Connect your Google account

1. In Google Cloud, enable the Google Drive API, configure the OAuth consent
   screen, and create an OAuth client of type **Web application**. If the app is
   in testing mode, add your Google account as a test user.
2. Register `http://localhost:8000/api/gdrive/callback` as an authorized redirect
   URI. Download the OAuth client JSON outside the repository.
3. Set `VOD_GDRIVE_CLIENT_FILE` to that JSON file before starting the backend:

   ```bash
   export VOD_GDRIVE_CLIENT_FILE="$HOME/.config/vod-review/google-client.json"
   uv run start --reload --port 8000
   ```

4. Click **Connect Google Drive**, authorize in the new tab, then return and click
   **Upload to GDrive**. Use the same browser hostname for the connect URL and
   callback so the authorization state cookie matches.

For a different backend address, set `VOD_GDRIVE_REDIRECT_URI` to the exact
registered callback URL. A frontend using a same-origin `/api` proxy can register
that frontend's callback URL instead. Tokens never go to frontend JavaScript.
The refresh token is saved with owner-only permissions at
`~/.config/vod-review/gdrive-token.json`; `VOD_GDRIVE_TOKEN_FILE` overrides it.
Keep both credential files out of source control. To change accounts, reconnect;
to revoke access, remove the app in your Google account's connected apps.
Testing-mode OAuth grants may expire and require reconnecting.

The app requests only `drive.file` access and creates a private folder named
`<video name> — round clips` in the connected account's My Drive. It does not
change sharing permissions. **Open Drive folder** links to the results.

## Progress, retries, and runtime

Encoding and uploading run in a background worker; the UI polls progress every
two seconds and recovers progress when returning to the video. Only one clip is
kept in temporary storage at a time. Drive receives resumable-protocol chunks of
at most 8 MiB. Failed batches show the number already uploaded and a retry button.
Retries keep completed clips and look up the failed clip's stable identifier to
recover a successful upload whose final response was lost. Interrupted transfers
restart that clip; temporary media is removed on success and failure.

Batch state is held in backend memory. Repeated clicks during the same server
session reuse the current batch when classification and settings match, including completed batches. Restarting or
reloading the backend loses batch state; a subsequent upload creates a new folder
and uploads all rounds again. Do not restart the backend during an upload. Clips
already uploaded remain in Drive after a failure. The source file, ffmpeg, Google
OAuth configuration, network access and sufficient Drive quota are required.
This uses the app's existing trusted local-user model, not multi-user account
isolation. No Google credentials are needed for the automated mocked tests.

Implementation: `backend/gdrive/router.py` handles OAuth and background work,
`backend/gdrive/utils.py` handles credentials, clipping and Drive requests, and
`frontend/src/DriveUpload.tsx` exposes the controls and progress.

## Validation

```bash
uv run pytest -q backend/tests/test_gdrive.py
cd frontend
npm test -- --run
npm run build
```

Protocol references: [Google web-server OAuth](https://developers.google.com/identity/protocols/oauth2/web-server)
and [Drive uploads](https://developers.google.com/workspace/drive/api/guides/manage-uploads).
