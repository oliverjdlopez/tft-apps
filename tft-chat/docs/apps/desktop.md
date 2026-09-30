# Electron desktop application

`desktop/` wraps the existing React frontend and FastAPI application in a native
Electron window. It starts the backend from the checkout automatically; it does
not bundle Python, create an installer, or replace any web application code.
See [Web runtime and browser UI](../architecture/web-runtime.md) for application
behavior shared with the browser.

## Desktop workspace tabs

The desktop window has **ChatTFT**, **Rolldown**, **Flowchart**, **VOD Review**, **Wisps**,
**Langfuse**, and **Database** tabs above the web application, plus **Compositions**
enabled by default. Use the buttons or **Ctrl+1** for ChatTFT, **Ctrl+2** for
Compositions, **Ctrl+3** for Rolldown, **Ctrl+4** for Flowchart, **Ctrl+5** for VOD Review,
**Ctrl+6** for Wisps, **Ctrl+7** for Langfuse, and **Ctrl+8** for Database (macOS: **Cmd**
instead of **Ctrl**). The six product tabs take the leading shortcuts in tab-bar order;
the two external integrations follow.
Switching views retains all pages, including chat state, the current Langfuse
page, and open CloudBeaver SQL editors and results. ChatTFT is selected initially. Native View-menu reload, zoom, and developer tools target the selected page.
Rolldown loads the application’s standalone `/rolldown` page in its own sandboxed
view and retains simulator state while hidden. It shares the managed Python
backend with ChatTFT and does not start another service.
Flowchart likewise loads the standalone `/flowchart` page in its own sandboxed view
with no preload and retains canvas state while hidden; see
[Flowchart patch workspaces](flowchart.md).
On **ChatTFT**, **Rolldown**, **Flowchart**, or enabled **Compositions**, **Force Reload** (**Ctrl+Shift+R** / **Cmd+Shift+R**) stops
the owned services, starts a fresh Python interpreter, and reloads all enabled ChatTFT application pages
after readiness checks. Production mode also rebuilds the frontend; development
mode restarts Vite and its backend proxy. This reloads imported Python code and
backend configuration without quitting Electron. In-flight work and unsaved page
state are interrupted. Repeated reload commands are ignored during restart.
Ordinary **Reload** refreshes only the page. Force Reload on Langfuse or Database
only bypasses that page’s cache; their Docker services remain independently managed.
The browser application uses Chat, Workflows, and Developer navigation.
Browser users can open `/rolldown` directly or via Developer → Status, and
`/flowchart` directly.
Developer → Status also links to the local CloudBeaver and Langfuse services
for browser access. The embedded database row browser has been removed; use
the Database workspace for table inspection and SQL.

Langfuse loads lazily from `http://localhost:15500/project/chattft-evals` in a
separate sandboxed `WebContentsView`. Its persistent Electron session remembers
login across desktop launches; sign in once inside Electron, independently of
your normal browser. No login credentials are injected into the page.

`npm start` and `npm run dev` check Langfuse web health on port 15500 and host-runner health over its private Unix socket before
opening Electron. If unavailable, they run the existing evaluation launcher
with the selected checkout Python (`--python` is respected), starting Docker
services and seeding missing content without opening a browser. A healthy web service and host runner are reused without rebuilding or reseeding.
A stopped host runner triggers the launcher even when the web UI is healthy. Startup logs appear in the launch terminal. The first
start may download/build images and takes up to 15 minutes, separately from
the application startup deadline.

Docker must already be installed and its daemon running. A startup failure
prints recovery instructions and continues opening ChatTFT. After resolving
the failure, start the stack from the repository root and use **Retry connection**:

```sh
uv run --extra evals chat-tft-evals up --no-browser
```

For WSL checkouts, automatic startup runs in WSL with its Python and Docker;
`setup:wsl` and `--help` do not start Langfuse. Windows must be able to reach the
published UI through localhost forwarding. Quitting desktop leaves the Docker
stack running; stop it explicitly with `uv run --extra evals chat-tft-evals down`. See [local Langfuse deployment](../development/langfuse-local.md)
for setup, credentials, and shutdown instructions.

An unavailable Langfuse page shows startup instructions and **Retry connection**
after a load failure or a 15-second timeout. A page crash also offers retry.
ChatTFT stays available independently. Links within the Langfuse origin stay in
its view; external HTTP(S) links open in the system browser.

The local desktop navigation has a narrowly scoped preload for tab switching
and retry. Main-process IPC accepts only its exact top-level frame and fixed
actions. No hosted application has a preload or Node access. Child views
are explicitly destroyed when their window closes.

## Database workspace (CloudBeaver)

The **Database** tab loads `http://localhost:8978` on first selection. It hosts
CloudBeaver Community 26.2.0 with the same independent 15-second loading deadline,
error screen, and Retry behavior as Langfuse. Reload, zoom, and developer tools
apply to the selected tab. Each external page has its own timer and failure state.

Start CloudBeaver separately from the repository root with Docker available:

```sh
docker compose -f desktop/cloudbeaver/compose.yaml up -d
```

The first visit opens CloudBeaver's setup wizard. Create your account, sign in,
and configure your PostgreSQL connections in CloudBeaver. Its separate persistent
Electron session (`persist:cloudbeaver`) retains login subject to server expiry;
your browser and Langfuse sessions remain separate. No repository credentials or
RDS settings are imported. Connection permissions come from the database account.

The independent `chattft-cloudbeaver` Compose project publishes only
`127.0.0.1:8978`. It mounts a named workspace volume at
`/opt/cloudbeaver/workspace`, with no repository mounts or connection to the
Langfuse network. Database connections originate inside this container:
`localhost` means the container itself. Use database hosts reachable from Docker
and configure the required PostgreSQL TLS settings and RDS network access.

For WSL checkouts, run Compose in WSL. Windows Electron must reach the published
port through Windows-to-WSL localhost forwarding, just as with Langfuse. A busy
port or unavailable Docker daemon prevents startup; inspect these commands:

```sh
docker compose -f desktop/cloudbeaver/compose.yaml ps
docker compose -f desktop/cloudbeaver/compose.yaml logs --tail 100
```

Resolve port conflicts on both Windows and WSL, then use **Retry connection**.
The desktop uses fixed port 8978; changing only Compose's mapping does not update
the desktop destination. CloudBeaver outages and renderer crashes affect only
its tab. Electron does not start or stop this service; quitting leaves it running.

Stop the service without deleting saved configuration:

```sh
docker compose -f desktop/cloudbeaver/compose.yaml down
```

The `chattft-cloudbeaver_workspace` volume retains CloudBeaver's configuration,
users, and saved workspace content. Back up this volume while the service is
stopped before upgrading or moving machines, and restore it with the same image
version before restarting. Never use `down --volumes` to perform a normal stop.
Database contents live in the connected databases and require their own backups.
The container uses `restart: unless-stopped`; Docker may restart it after reboot.

## Setup on Windows and macOS

Use native Node **22.12 or newer within Node 22**, npm, and Python **3.13+**.
Install [uv](https://docs.astral.sh/uv/getting-started/installation/) to prepare
the Python environment. For a native Windows checkout, use Windows Node/Python.
For an existing WSL checkout, use the WSL setup below instead. On macOS, use
native installations appropriate for the machine's architecture. Do not copy
`.venv` or `node_modules` between operating systems.

From the repository root, these commands work in PowerShell and a macOS shell:

```sh
uv sync --locked
npm --prefix app/frontend ci
npm --prefix desktop ci
```

The desktop install downloads the pinned Electron binary using its postinstall
script. Network access is needed for initial dependency installation. Desktop
launch does not install host dependencies; Langfuse startup can download Docker
images and build its experiment-service dependencies. If install scripts were disabled, rerun the
desktop install with scripts enabled before launching.

Configure `chat_tft.ini` and `.env` as for the browser application; see
[Configuration](../configuration.md). Electron does not copy, display, or inject
these secrets into the renderer. The existing backend still reads them normally.
Missing database credentials retain the browser's degraded-mode warning.

## Existing WSL development on Windows

You **do not need Windows Python, a second checkout, or a second Python
virtual environment**. Windows runs only the Electron window. Your existing WSL
user, Node executable, Python `.venv`, frontend dependencies, environment
variables, `.env`, INI, source files, and resource paths remain in WSL.

Requirements: WSL 2 with Windows executable interoperability enabled, Linux Node
22.12+ within Node 22, and Windows Node 22.12+ within Node 22 **including npm**.
Install the standard [Windows Node distribution](https://nodejs.org/en/download)
if needed, then reopen your WSL terminal so Windows PATH changes are visible.
This launcher does not require WSLg.

From your **WSL terminal**, prepare only dependencies you have not installed yet:

```sh
uv sync --locked
npm --prefix app/frontend ci
cd desktop
npm run setup:wsl
```

`setup:wsl` installs the locked Windows Electron dependencies under
`%LOCALAPPDATA%\ChatTFT Desktop\runtime`, keyed by the lockfile and Windows
architecture. It requires network access and does not install Linux Electron or
write Windows dependencies into the checkout. You can skip `npm ci` in
`desktop/` for this WSL workflow: the bootstrap uses Node built-ins only.
Quit any running desktop windows before repeating setup when the desktop
lockfile changes.

Then, from that same WSL `desktop/` directory:

```sh
npm start          # build in WSL, start Python in WSL, open Windows Electron
npm run dev        # Python + Vite in WSL, Windows Electron with hot reload
```

WSL is detected automatically through `WSL_DISTRO_NAME`. Both commands start all
required services; you do not start a separate backend terminal. Keep the launch
terminal open. Closing it or pressing Ctrl+C stops the app and its managed
services. Closing the last Windows window also stops its WSL services.

If Windows Node is not on Windows PATH, select its **WSL-visible executable
path**, either persistently in your shell configuration or for each command:

```sh
export CHATTFT_WINDOWS_NODE='/mnt/c/Program Files/nodejs/node.exe'
npm run setup:wsl
npm run dev -- --port 8301 --dev-port 5174
# Equivalent one-command executable override:
npm start -- --windows-node '/mnt/c/Program Files/nodejs/node.exe'
```

`--python` continues to mean a **Linux** executable in this mode. By default it
uses the current checkout's `.venv/bin/python`. For a worktree sharing another
checkout's environment, select it explicitly:

```sh
npm run dev -- --python /home/me/project/.venv/bin/python
```

The Windows bootstrap stages only the small desktop shell files into its cache
on each launch. React is always built/served in WSL, and edits stay in your
original checkout. Shell staging is keyed by content so edits cannot overwrite
files used by a running window. Old runtime/shell cache versions can be removed
manually after quitting the app; they do not contain the application database or
Python environment. Browser storage remains in the separate Windows Electron
profile, identified by WSL distribution, user, and checkout.

Windows reaches both managed services through `127.0.0.1`. WSL's default NAT
localhost forwarding or mirrored networking must permit that connection; see
[Microsoft's WSL networking documentation](https://learn.microsoft.com/en-us/windows/wsl/networking).
Services remain bound to loopback. The launcher does not change firewall rules,
networking settings, or the WSL distribution configuration. Before loading the
UI it verifies a random per-launch identity from **each** service, so an unrelated
Windows server on the same port cannot satisfy readiness. Choose other ports
if a Windows or Linux application already uses them.

Windows Electron invokes `wsl.exe` with the exact distribution, Linux user,
checkout directory, and Linux Node executable. Each invocation starts a Linux
pipe guardian which owns one Python/build/Vite process group. Commands and
arguments are passed directly without a shell; the original WSL environment
travels through private process pipes, never command-line arguments or cache
files. Shutdown/pipe EOF propagates across the boundary. The guardian requests
graceful shutdown, then kills only its owned process group after twelve seconds
if necessary. Windows waits up to twenty seconds before its bounded fallback.
Windows Node owns a private local named pipe to Electron because Windows GUI
executables do not reliably inherit stdin. Quit and bootstrap disconnection
use that pipe; the Linux guardians use stdin pipes. This named-pipe transport
also applies to native Windows checkouts.
No `wsl --shutdown`, distribution termination, or process-name killing is used.

## Launch modes

From `desktop/`:

```sh
npm start
```

Normal launch builds the current frontend with its existing Vite configuration,
then starts Python and loads the UI served by FastAPI. The build regenerates
the ignored `app/frontend/dist` directory. A failed build stops startup rather
than displaying an older build. Source edits become visible on the next launch.

```sh
npm run dev
```

Development launch starts Python and a loopback Vite server. Electron loads
Vite's development UI, with frontend hot reload. The Vite configuration is
reused, with `/api` and `/static` proxy targets pointing to the actual desktop
backend port. This mode does not require a production frontend build. Vite may
write its normal ignored caches. For Python code changes, use **Force Reload**
on the ChatTFT tab or quit and restart the desktop app; backend reload workers
are deliberately disabled.

Both modes display startup progress and wait for HTTP readiness. Database
warmup and any configured synchronous startup catch-up remain part of backend
startup. The default startup deadline is 120 seconds, including the build.

## One-run options

Pass arguments after npm's `--` separator:

```sh
npm start -- --port 8301 --startup-timeout 300
npm run dev -- --port 8301 --dev-port 5174
npm start -- --python "C:\My Environments\chattft\Scripts\python.exe"
npm start -- --python /Users/me/environments/chattft/bin/python
npm start -- --help
```

| Option | Default | Behavior |
| --- | --- | --- |
| `--python` | Checkout `.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on macOS | Native executable path or executable name on PATH; custom environments must have project dependencies installed. Relative paths resolve from the launch directory. |
| `--port` | `[chat] ui_port`, normally `8300` | Backend port; desktop always binds `127.0.0.1`, independently of `[chat] ui_host`. |
| `--dev-port` | `5173` | Vite port in development mode; never silently switches to another port. |
| `--startup-timeout` | `120` seconds | Startup deadline, configurable from 1 to 3600 seconds. |

Options do not rewrite INI or environment files. Backend and frontend ports
must be different in development mode. When either port is occupied, stop the
other application or choose another port. Desktop never adopts or terminates
a separately started server.

## Process lifetime and browser parity

The Node bootstrap starts Electron with the appropriate service Node executable
path and parent-lifetime connection.
For native checkouts, Electron directly owns the Python launcher and any
frontend build/Vite process. In WSL mode it owns those services through the
Linux guardians described above. Services are not spawned through a shell. The Python launcher excludes its own script directory from Python module lookup
so `desktop/utils.py` cannot shadow the backend namespace package `utils`. It
reserves its socket before announcing its port, then runs the existing `api.app:app` with
one Uvicorn worker. The parent probes `/api/config` only after that ownership
event and probes the frontend before showing the application.

On Windows, closing the last window quits and stops the managed services. On
macOS, closing the window keeps the application and services running; clicking
the Dock icon restores the window. Use Quit or Cmd+Q to stop everything. A
second launch of the same checkout focuses its existing application. Different
checkouts have separate desktop profiles, but need different ports when run
simultaneously.

Quit sends a shutdown request over each child's stdin pipe. Python translates
it into Uvicorn graceful shutdown, with a five-second request drain limit.
Pipe EOF also triggers shutdown if a parent disappears. A Python watchdog
forces exit after ten seconds if imports, startup, or shutdown are stuck;
Electron allows twelve seconds before forced child termination. Cleanup is
limited to owned processes. Forced shutdown can interrupt in-flight work, so
finish important edits and operations before quitting.

The application uses its existing layout, styles, API calls, stream parser,
confirmation dialogs, and React state. Standard native menus provide editing,
reload, zoom, fullscreen, and developer tools. External HTTP(S) links, including
OpenAI trace links, open in the system browser; other external schemes are
blocked. Renderer Node access is disabled, with sandboxing and context isolation
enabled. The hosted application views have no preload or privileged renderer bridge;
only the local desktop navigation has the limited bridge described above. Permission
handlers allow clipboard writes only from the application origin.

Electron stores browser data in its own persistent, per-checkout profile under
the OS application-data directory. It does not import Chrome/Safari storage.
Production and development use different origins, so their local storage is
separate; changing a port also changes the origin. Window controls and font
rendering follow the host OS. Existing backend behavior still writes traces and
performs explicit spec/eval edits in the checkout, just as in the browser.

## Troubleshooting

- **WSL Windows Node missing:** install Windows Node 22 with npm, or set
  `CHATTFT_WINDOWS_NODE` to its WSL-visible `node.exe` path. Linux Node cannot
  substitute for the native Windows shell runtime.
- **WSL Windows Electron missing:** run `npm run setup:wsl` in `desktop/` from
  WSL; launching does not download dependencies.
- **WSL localhost timeout/wrong server:** check Windows-to-WSL localhost
  forwarding, firewall policy, and conflicting ports on both systems. Use
  `--port` and `--dev-port` to choose free ports. The terminal retains service
  diagnostics; no networking settings are changed automatically.
- **WSL interoperability error:** verify `powershell.exe` runs from the WSL
  terminal and that Windows executables are allowed by the WSL configuration.
- **Missing Electron (native checkout):** run `npm --prefix desktop ci` from the repository root.
  An unavailable Electron binary is reported in the terminal because no desktop
  window can be created yet.
- **Missing Python or dependencies:** run `uv sync --locked` in the checkout,
  or pass `--python` for an environment containing the application dependencies.
- **Frontend dependency/build error:** run `npm --prefix app/frontend ci` and
  inspect the launch terminal's Vite diagnostics.
- **Busy port:** stop the other service or change `--port` / `--dev-port`.
  On Windows, an exclusive socket can remain unavailable briefly while old
  connections finish closing; wait and Retry after a recent shutdown.
- **Startup timeout:** inspect backend startup logs and configuration. Increase
  `--startup-timeout` if an intentional synchronous catch-up takes longer.
- **Unexpected service exit:** use Retry to clean up and restart the complete
  runtime. Retry does not install dependencies. If a child could not be stopped,
  the dialog offers Quit instead of starting competing services.

### Missing Tailwind package or Python 3.14 CUDA wheel

Run frontend commands from the repository root with `--prefix app/frontend`;
there is no `desktop/frontend` directory. If Vite cannot resolve
`@tailwindcss/vite`, refresh the installed packages from the committed lockfile:

```sh
npm --prefix app/frontend ci
npm --prefix app/frontend run build
```

Python dependency installation does not install frontend packages. Normal
desktop setup uses `uv sync --locked`; add `--extra evals` for host evaluation
commands. `--all-extras` also selects the optional `compositions-gpu` extra.
The locked CuPy 13.6.0 package has no CPython 3.14 wheel, so that combination
fails even though the base project permits Python 3.14. To retain Python 3.14
and install all other extras, use:

```sh
uv sync --locked --all-extras --no-extra compositions-gpu
```

For the CUDA compositions extra, select Python 3.13 explicitly instead:

```sh
uv sync --locked --python 3.13 --all-extras
```

Selecting a different Python version can recreate the checkout environment;
quit the desktop application first. These commands install dependencies only
for ChatTFT. Each video checkout needs its own environment and frontend install.

## Validation

Run from the repository root:

```sh
npm --prefix desktop test
uv run python -m unittest discover -s desktop/tests -p 'test_*.py' -v
npm --prefix app/frontend test
npm --prefix app/frontend run build
uv run pytest -q
```

Desktop Node tests cover Force Reload restart ordering, repeated reload commands,
external-page isolation, startup retry and failed cleanup, plus path handling, navigation/permission boundaries,
readiness, busy ports, build failure/retry, timeouts, and owned-process cleanup
using isolated HTTP fixtures. WSL tests additionally cover literal cross-OS
arguments, immutable shell staging, wrong-server rejection, Linux guardian
shutdown on command/EOF, missing executables, and forced cleanup. They also run the actual Vite build and verify
development proxy overrides, so install frontend dependencies before running
them. Python tests exercise the actual Uvicorn launcher
against an in-memory ASGI application, including parent loss during stalled
startup. They require local socket access and make no model or database calls.
The Python tests are also collected by the full pytest command. Desktop workspace
tests cover retained workspace views, configurable composition visibility, independent external-page timeouts/retries,
session isolation, navigation/IPC restrictions, and child cleanup. Desktop Node
tests remain an explicit local check; the existing CI workflow is unchanged.

`desktop/tests/workspace-electron.mjs` is an opt-in native Electron test entrypoint
using local page fixtures and a temporary profile. Run it with an installed native
Electron executable. Set `CHATTFT_TEST_CLOUDBEAVER=1` to additionally load the real
CloudBeaver service at port 8978; this check reads its UI without configuring an
account or database connection. Set `CHATTFT_TEST_SCREENSHOT` to an optional native
output path to capture the live page. The fixture checks real shell IPC, retained
editor state, isolation, offline recovery, and renderer cleanup.


On native Windows and macOS, manually check both launch modes: initial layout,
resizing, all tabs, streamed chat and Activity events, inline analytics, copy,
spec/eval confirmations, trace links, preference persistence, and degraded
database mode. Confirm dev hot reload and normal-build freshness, close/reopen
behavior, Retry after failures, and absence of owned services after Quit. Use
disposable content for mutation checks. A Linux process test does not substitute
for native Windows/macOS GUI validation.

For WSL, repeat Windows GUI checks from the existing WSL checkout. Verify both
launch modes, frontend hot reload, Windows and Linux port conflicts, custom
Python paths, Ctrl+C/terminal loss, and service cleanup without affecting other
WSL work. Linux guardian tests alone do not validate Windows interoperability.

For an automated native Windows-to-WSL check, from WSL `desktop/` run:

```sh
npm run test:wsl
# Same executable and Python overrides as a normal launch:
npm run test:wsl -- --windows-node '/mnt/c/Program Files/nodejs/node.exe' --python /home/me/project/.venv/bin/python
```

This opt-in check uses Windows Node to supervise the real WSL Vite/Uvicorn
workers with a minimal ASGI fixture. It checks both modes, parent EOF, abrupt
`wsl.exe` loss, Windows port conflicts, and cleanup without making model or
database calls. It does not open Electron or replace the GUI checklist above.

### Native workspace regression

With native Electron dependencies installed, run from `desktop/`:

```sh
npx --no-install electron tests/workspace-electron.mjs
```

This opt-in check runs the real Electron views and preload against fixture HTML
in a temporary profile. It verifies tab state retention, renderer isolation,
Langfuse connection failure/retry, and child cleanup without Docker, credentials,
or model calls. For WSL, invoke the Windows Electron executable installed by
`setup:wsl` with the Windows-visible path to this test script. The default Node
suite covers the same workspace state and navigation boundaries without a GUI.

## Automatic VOD Review and Wisps startup

Desktop starts both video workspaces in the background, independently of ChatTFT
readiness. Each backend and frontend is checked separately: compatible running
services are reused, and only missing services are started. No processes are
stopped to free an occupied port. An incompatible service or a probe timeout
leaves that workspace unavailable; resolve the conflict and press Retry.

| Workspace | Default checkout | Backend | Frontend |
| --- | --- | --- | --- |
| VOD Review | `~/vod-review` | 8000 | 5174 |
| Wisps | `~/vod-review-wt2` | 8001 | 5175 (`/wisp_classifier`) |

The Wisps checkout must include the Wisps API and page. Set `CHATTFT_VOD_REPO`
or `CHATTFT_WISPS_REPO` to an absolute checkout path before launching Electron
to override these defaults. In WSL these are Linux paths from the launch shell.
Each checkout must already have its own `.venv` and frontend npm dependencies;
startup does not install dependencies or change branches. Managed backends run
in fresh interpreters without auto-reload workers.

For checkouts under `~/Desktop`, launch from the ChatTFT repository root with:

```sh
export CHATTFT_VOD_REPO="$HOME/Desktop/vod-review"
export CHATTFT_WISPS_REPO="$HOME/Desktop/vod-review-wt2"
npm --prefix desktop start
```

A `vod backend executable was not found` or `wisps backend executable was not
found` error can indicate the wrong checkout path as well as a missing Python
environment. Verify the applicable override and that checkout's
`.venv/bin/python` (`.venv/Scripts/python.exe` on Windows). The desktop `--python`
option selects ChatTFT's interpreter; video workspaces always use their own
checkout environments. Install frontend dependencies in each video checkout's
`frontend` directory before Retry.

Existing backends are recognized by their OpenAPI title and required video
endpoints; Wisps additionally requires the Wisps endpoint. Existing frontends
must expose the workspace identity and correct backend destination supplied by
`desktop/vod-frontend.mjs`. A frontend started with an older version of that
launcher must be stopped once, then Retry lets Desktop start the updated version.
Recognition checks API compatibility at the configured port, not the source
checkout or Git revision of an already-running backend.

Frontends proxy `/api` to their corresponding backend, including video playback
and uploads, without changing either repository's CORS settings. All newly
started services bind to loopback. WSL starts them using the original Linux
Node, environment, and checkout Python; ownership identity checks also verify
Windows-to-WSL localhost forwarding for newly started services.

Quitting Electron stops only processes it created. Services already running
before launch stay running. Startup failure cleans up only newly created
processes for that workspace, leaving the other workspaces available. Retry
repeats discovery and starts anything still missing. Force Reload on VOD Review
or Wisps remains a page refresh; ChatTFT Force Reload does not restart video
services or interrupt their jobs. Quitting will interrupt jobs in backends
started by Electron.

Manual startup remains supported, using separate terminals:

```sh
cd ~/vod-review
uv run start --reload --port 8000
```

```sh
cd ~/vod-review-wt2
uv run start --reload --port 8001
```

From the ChatTFT repository, launch each frontend separately:

```sh
node desktop/vod-frontend.mjs
node desktop/vod-frontend.mjs --wisps
```

Use `--repo /absolute/checkout` with either frontend command if needed. The
combined VOD `vod-review-start` command uses frontend port 5173 and is not the
launcher for these desktop endpoints.

## Compositions workspace

**Compositions** at `/compositions` is enabled by default through
`[chat] composition_workbench = true`. Install `uv sync --extra compositions`
for its algorithms. Offline usage remains disabled by default
(`composition_offline = false`). Set the workbench setting to `false` and restart
Desktop to hide it. It uses a separate
sandboxed `WebContentsView` with no preload, sharing ChatTFT's backend and navigation
restrictions. Switching tabs retains family, example, form, and section state. Normal
Reload refreshes only its page; Force Reload on any application workspace restarts
the shared backend and reloads ChatTFT, Rolldown, Flowchart, and enabled Compositions. Shutdown
closes its renderer and interrupts any owned experiment worker; saved runs remain.
Disabled installations hide the tab and cannot invoke its API. See the
[composition guide](../architecture/compositions/index.md).

## Shared interface styling

`workspace.css` and `status.css` mirror the light lilac surfaces, system typography,
iris actions, and focus treatment from `app/frontend/src/theme.css`. The shell
remains plain HTML/CSS with 48px navigation; shortcuts, retained views, and service
ownership are unchanged. Both stylesheets are part of content-addressed Windows
shell staging, so restart after changes to load the new staged asset set.
See [shared UI conventions](../development/shared-ui.md) and
[migration validation](../development/shared-ui-validation.md).
