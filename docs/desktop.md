# Suite desktop architecture and setup

`desktop/paths.mjs` resolves the suite, desktop, ChatTFT and VOD roots.
Electron runs natively; separate Docker images own each application's Python
runtime and frontend dependencies. Their dependency locks remain independent.

Run `node scripts/setup.mjs` from the suite root. It installs only the native
Electron shell on the host and builds the application and development images.
`python3 scripts/setup.py` remains a compatibility wrapper. Setup starts no app.
Host prerequisites are Node 22.12+ within Node 22, Docker Engine/Compose, and
configured NVIDIA container access for GPU VOD processing. Use
`TFT_DOCKER_GPU=0 npm start` for explicit CPU operation.

From `desktop/`, `npm start` launches the prepared images. ChatTFT serves its
built frontend and API at port 8300. VOD serves its built frontend and API at
both local ports 8000 and 5174. `npm run dev` runs Vite inside separate containers
on ports 5173 and 5174, proxying to their respective Python services.
Each app has a unique Compose project for its desktop lifetime. Readiness checks
verify its fresh identity; failure and quit clean up only that project's
containers and network, retaining all mounted data. VOD Review remains one
persistent view. See [container lifecycle](docker-desktop.md) for supervision,
recovery, image rebuilds and validation. The former Wisps tab was removed.

The **Media** tab (Ctrl/Cmd+9) browses the suite-owned shared media
catalogue through ChatTFT's owned backend, in both production and development
modes. Browse video, audio, images, text/transcripts and data; select a resource
to preview it and copy its portable reference. Refresh
reloads the catalogue and Load more retrieves further pages. Tab switches retain
the selection and search. See [media browsing](shared-media.md#desktop-media-browser)
for supported resources and publication. The browser does not start another
backend or run transcription.

VOD creator-import schedules run once in the VOD backend, independent of
whether the VOD tab is visible. The schedule persists in the app-local VOD database;
closing the desktop stops its poller, with the most recent missed daily window
checked on restart. See [automatic creator imports](../vod-review/docs/creator-imports.md).

ChatTFT defaults to backend port 8300 and development frontend port 5173.
Pass `--port`, `--dev-port` or `--startup-timeout` after npm's `--` separator.
The legacy `--python` option is accepted but unused for container services. VOD retains fixed ports 8000 and 5174. Occupied application ports
fail explicitly; compatible servers from the original checkouts are never adopted.
Socket binding, strict Vite ports and per-launch identity checks enforce ownership.

Electron stores profiles and Windows shell caches under the `tft-apps` application
data identity. Renderer sandboxing, navigation checks, context isolation, shell
IPC checks, readiness probes and pipe shutdown remain enabled. WSL forwards the
exact Linux suite root, Node worker, process working directory, distribution,
user and environment over private pipes. Run `npm run setup:wsl` once from
`desktop/` using Linux Node with Windows Node 22 installed. Python and frontend
dependencies live in the Docker images; Docker commands run in WSL. Windows GUI validation is reported separately.
Windows shell staging includes both media scripts; the renderer requests
catalogue resources over the existing owned backend URL across the WSL bridge.

Langfuse uses Compose project `tft-apps-evals`, project ID `tft-apps-evals`, new
project-scoped volumes, generated credentials in ignored
`tft-chat/evals/langfuse/.env`, host port 15510 and runner state under that
application's `.runtime/`. CloudBeaver uses `tft-apps-cloudbeaver`, a fresh workspace
volume and host port 8979 (container port 8978). Start CloudBeaver explicitly with
`docker compose -f desktop/cloudbeaver/compose.yaml up -d` from the suite root.
Neither stack shares volumes or runners with the original services.

The legacy `chattft-evals` project on port 15500 was stopped after the
2026-10-06 expert-dataset cutover. Its volumes are retained for recovery; normal
desktop and evaluation launches use only `tft-apps-evals` on port 15510. See the
[cutover record](migration.md) for preserved historical results.

The Langfuse desktop tab reads `LANGFUSE_DESKTOP_URL`,
`LANGFUSE_INIT_USER_EMAIL`, and `LANGFUSE_INIT_USER_PASSWORD` from that ignored
file in Electron's main process. It accepts only a loopback HTTP(S) URL, reuses
an existing session, and otherwise signs in before opening the project page.
The credentials are never passed to the hosted renderer. Set
`LANGFUSE_DESKTOP_AUTO_LOGIN=false` for manual sign-in; a failed automatic
sign-in also leaves the normal sign-in page available.

Host virtual environments remain optional for contributor tests and standalone
troubleshooting; normal desktop startup does not use them.

Use the [ChatTFT backend guide](../tft-chat/docs/architecture/web-runtime.md) or
[VOD guide](../vod-review/README.md) for standalone troubleshooting commands. Run
Python suites from each application root and desktop tests with `npm test` from
`desktop/`; run desktop Python tests from `tft-chat/` with
`.venv/bin/python -m pytest ../desktop/tests -q`. Database tests require isolated
complete `RDS_TEST_*` targets ending in `_test`.

Inherited VOD data/cache paths and OAuth token storage are redirected to the
destination; the external Google OAuth client file reference is retained. Tracing
uses the destination platform keys. Both backends receive the suite-owned
`TFT_MEDIA_DIR=<suite>/media`, enabling shared downloads and portable resource
references. See [media sharing](shared-media.md) for APIs and storage lifecycle.

Opt-in real application smoke (Linux/WSLg): from `desktop/`, run
`env -u ELECTRON_RUN_AS_NODE node_modules/electron/dist/electron --disable-gpu tests/suite-electron.mjs`.
It uses a private temporary Electron profile and VOD directory under `.migration/`,
disables application RDS access, loads all five product views, and checks owned
process shutdown on close. Application ports must be free. The simpler
`tests/workspace-electron.mjs` smoke covers navigation, IPC and recovery with
local HTML fixtures.

If original services occupy the normal application ports, add
`--disposable-ports` to the smoke command. This test uses ephemeral ports for its
owned services and view URLs; normal desktop launch retains the fixed defaults
and rejects occupied ports.

The native Windows wrapper keeps its Windows environment for locating
`wsl.exe`; the selected Linux application environment is sent exclusively over
the private worker pipe, including its process working directory.
