# Suite desktop architecture and setup

`desktop/paths.mjs` and `desktop/paths.py` resolve the suite, desktop, ChatTFT and
VOD roots. Commands work independently of the current terminal directory. The
Electron shell owns separate Python interpreters in `tft-chat/.venv/` and
`vod-review/.venv/`; dependencies are never combined.

Run `python3 scripts/setup.py` from the suite root. It installs locked Python
extras (evals, compositions and transcription for ChatTFT; transcription for VOD)
and locked Node dependencies for both frontends and desktop. It starts no service.
Installers and packaging are outside this migration.

From `desktop/`, `npm start` builds ChatTFT's production frontend and serves it
through FastAPI; `npm run dev` uses Vite hot reload. VOD retains its Vite serving
mode in both desktop modes. Separate sandboxed persistent VOD Review and Wisps
views load `http://localhost:5174/` and `/wisp_classifier` from the same frontend
and one backend on port 8000. A shared startup promise coalesces concurrent tab
loads and retries. Failure marks both video views unavailable; retry cleans up
before creating a new runtime. Quit stops only the owned service trees.

VOD creator-import schedules run once in that shared backend, independent of
which video tab is visible. The schedule persists in the app-local VOD database;
closing the desktop stops its poller, with the most recent missed daily window
checked on restart. See [automatic creator imports](../vod-review/docs/creator-imports.md).

ChatTFT uses its copied configured backend port (normally 8300); dev Vite uses
5173. Pass `--port`, `--dev-port`, `--python` or `--startup-timeout` after npm's
`--` separator. VOD retains fixed ports 8000 and 5174. Occupied application ports
fail explicitly; compatible servers from the original checkouts are never adopted.
Socket binding, strict Vite ports and per-launch identity checks enforce ownership.

Electron stores profiles and Windows shell caches under the `tft-apps` application
data identity. Renderer sandboxing, navigation checks, context isolation, shell
IPC checks, readiness probes and pipe shutdown remain enabled. WSL forwards the
exact Linux suite root, interpreter, process working directory, distribution,
user and environment over private pipes. Run `npm run setup:wsl` once from
`desktop/` using Linux Node with Windows Node 22 installed. Python and frontend
dependencies remain in WSL. Windows GUI validation is reported separately.

Langfuse uses Compose project `tft-apps-evals`, project ID `tft-apps-evals`, new
project-scoped volumes, generated credentials in ignored
`tft-chat/evals/langfuse/.env`, host port 15510 and runner state under that
application's `.runtime/`. CloudBeaver uses `tft-apps-cloudbeaver`, a fresh workspace
volume and host port 8979 (container port 8978). Start CloudBeaver explicitly with
`docker compose -f desktop/cloudbeaver/compose.yaml up -d` from the suite root.
Neither stack shares volumes or runners with the original services.

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
disables application RDS access, loads all six product views, and checks owned
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
