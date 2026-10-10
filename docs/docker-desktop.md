# Desktop container lifecycle

The Electron desktop uses one Node container worker for ChatTFT and one for VOD
Review. Application Python environments and frontend builds live in their Docker
images. Starting the desktop does not run a host Python interpreter, install
dependencies, or build a frontend on the host. Prepare the images during setup
before launching the desktop. The legacy `--python` option is accepted for
compatibility but does not select an application runtime.

| Application | Production | Development |
| --- | --- | --- |
| ChatTFT | Backend and built frontend at port 8300 | Backend at 8300; Vite at 5173 |
| VOD Review | Backend at 8000, with the same built frontend/API also published at 5174 | Backend at 8000; Vite at 5174 |

ChatTFT accepts `--port` and `--dev-port` overrides after npm's `--` separator.
The container desktop defaults to backend port 8300; it does not discover a
different backend port through a host Python configuration command. VOD keeps
its existing fixed default ports. See [desktop architecture](desktop.md) for the
window, tabs, application roots, and independent supporting services.

`DesktopRuntime` starts `desktop/container-worker.mjs` with a service name, mode,
backend/frontend ports, and a fresh launch identity. `VideoRuntime` selects VOD's
service, ports, and health endpoint while sharing the same supervision. Each
runtime coalesces concurrent starts into one promise and owns only its worker.
It awaits the worker's `bound` and `listening` records, verifies that reported
ports match the request, checks the launch identity at both distinct HTTP
endpoints, and waits for the application's health endpoint and frontend.
Occupied ports and mismatched identities fail startup instead of adopting a
server from another checkout.

Workers retain the parent pipe until shutdown. Startup failure or timeout stops
the owned worker; an unexpected exit after readiness marks its application
unavailable. Retry creates a fresh runtime after cleanup. Desktop quit requests
cleanup once and waits up to 60 seconds before forced process termination.
A worker's `cleanup_error` record or forced termination remains a visible failure
so a retry cannot mistake a surviving container project for completed cleanup.

On WSL, the Windows Electron shell invokes the existing Linux guardian with the
original distribution, Linux Node, checkout, and user. Worker arguments and the
Linux environment travel over its private pipe; the Windows wrapper retains its
native environment to locate `wsl.exe`. The guardian gives the worker 45 seconds
for cleanup and reports forced termination. The application Python interpreters
remain inside containers. The Linux launch bootstrap also ensures Langfuse using
the Node Docker launcher before opening the Windows shell.

## Image setup and rebuilds

Run `node scripts/setup.mjs` from the suite root for initial setup. Rebuild images
after code or dependency changes with `node desktop/docker.mjs build`, then
restart the desktop. Development mounts authored Python and frontend sources;
frontend hot reload stays active, while Python changes require the desktop's
Force Reload. Production Python code and frontend assets come from the image.
The specification editor retains a writable mount of the authored specs so its
edits remain visible in the checkout and evaluations. Exported gameplans, local
traces, diagnostic logs, asset caches and composition history also retain writable
local storage.

Compose descriptions are generated privately under `.runtime/docker/config/`,
with owner-only permissions and literal dollar signs escaped. They are removed
after successful shutdown. Failed cleanup retains its description for recovery:
inspect the corresponding `tft-apps-chat-<identity>` or `tft-apps-vod-<identity>`
project and use that file with `docker compose -p <project> -f <file> down`.
Never add `--volumes`; data and model caches remain local bind mounts.

Existing suite media and VOD data are mounted at their original absolute paths.
Chat's INI configuration is mounted read-only; application dotenv values and
explicit model/RDS/AWS environment overrides are supplied at runtime. External
AWS and Google client files are mounted separately. Secrets and local data are
excluded from every image build context. Full external RDS coordinates remain
unchanged. A host-only localhost database or tunnel needs a reachable host
address such as `host.docker.internal`; that hostname does not make a
loopback-only listener reachable automatically. No RDS data is moved.

VOD GPU passthrough is requested by default. On Linux/WSL Docker Engine, configure
the [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
and verify GPU access first. Windows Docker Desktop uses its WSL2 GPU support.
GPU hardware and drivers remain on the host. Set `TFT_DOCKER_CHAT_GPU=1`
when the ChatTFT container also needs GPU transcription; it is optional for chat. `TFT_DOCKER_GPU=0` omits the GPU
request and configures transcription for CPU/int8. Setup never installs or
changes host GPU drivers or Docker's daemon configuration.

## Evaluation runner

`node desktop/docker.mjs langfuse-up` retains the existing `tft-apps-evals`
project, credentials, volumes, snapshots and runtime queue. The `experiments`
service runs the real evaluation server using the ChatTFT image. It has no
published host port and communicates with Langfuse over the Compose network.
ChatTFT joins this existing external network for tracing, using the internal
web-service address. If the network is absent, chat still starts with tracing
disabled for that launch; the loopback-only UI port is not used as a container
gateway. Restart chat after bringing Langfuse up to attach its network.
The launcher verifies an idle queue, stops ingress, checks again, and retires
only a legacy host process whose command owns this suite's exact socket.
A hidden or unverifiable live process blocks migration. Accepted queued, running
or awaiting-score jobs block migration, restart and shutdown. No paid evaluation
is submitted by setup or migration. Desktop quit leaves this supporting stack up.

Use `node desktop/docker.mjs eval-restart` after runner source/config changes,
`node desktop/docker.mjs eval-down` to stop the stack without deleting data, and
`node desktop/docker.mjs eval-compose logs --tail 100 experiments` for logs.
A private `docker-lifecycle.lock` directory serializes these operations. If a
launcher is killed, verify its recorded owner has stopped before removing only
that lock directory and retrying. The legacy Python lifecycle CLI delegates to
these Node commands; a host Python environment is optional.

## Validation

Run desktop tests from `desktop/`:

```sh
node --test tests/runtime.test.mjs tests/video-runtime.test.mjs tests/runtime-environment.test.mjs tests/wsl.test.mjs tests/paths.test.mjs tests/reload.test.mjs
```

These tests use isolated Node HTTP fixtures and actual child-process lifetimes.
They cover one-worker startup, both launch modes, identity and port rejection,
startup failure/retry, parent shutdown, cleanup errors, and the existing reload
and WSL bridge behavior. They do not build images or launch Docker applications;
image startup and a native Windows/Electron smoke remain separate checks.

After building images, run `node tests/container-smoke.mjs` from `desktop/`.
It starts the real images in both modes with disposable configuration/data,
no external database or model keys, and explicit CPU mode. It checks HTTP,
desktop identity, bidirectional local file access, and container cleanup with
state retained. This does not establish GPU inference or Windows GUI acceptance.

### Verification on 2026-10-09

- All four application/frontend images built successfully from the committed
  lockfiles. VOD's image includes the timezone data required by replay scheduling.
- All 87 desktop tests and 47 focused Python entrypoint/evaluation lifecycle tests
  passed. Two focused diagnostic-log tests also passed; the container configuration
  tests passed again after the final ownership-check changes.
- Real Docker acceptance passed for ChatTFT and VOD in both production and
  development: HTTP readiness, launch identity, frontend proxying, bidirectional
  local storage access, and removal of owned containers with data retained.
- The evaluation server passed an isolated non-root, read-only-image health check
  with networking disabled. VOD's Torch, ONNX Runtime, CTranslate2 and PyAV imports
  passed, as did loading the CUDA 12 cuBLAS library. No model inference was run.
- A broader existing database instrumentation test still fails because it patches
  the absent `_rds_iam_target` symbol; its test and database session module were
  unchanged by this migration.

Live cutover remains separate. Docker's GPU probe reported no configured NVIDIA
GPU vendor; host toolkit setup was not performed because automatic approval
review could not authorize the administrator-access check due to an account
usage limit. The legacy evaluation runner remained reachable outside the
execution sandbox's visible process namespace, so the ownership preflight
correctly refused to replace it. Run the handover from the owning WSL session
after its queue is idle. Native Windows/Electron GUI and GPU inference acceptance
remain unverified. Existing evaluation services and data were preserved.
