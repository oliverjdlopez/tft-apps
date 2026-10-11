# Local Langfuse deployment

The evaluation platform lives under `evals/langfuse/`. Docker Compose runs
Langfuse web and worker, PostgreSQL, ClickHouse, Redis, MinIO, and a small
webhook forwarder. The Python ChatTFT experiment service runs on the Linux/WSL
host, using the same local database connections as the application. The application itself does not depend on this stack.
The deployment follows [Langfuse's official Compose setup](https://langfuse.com/self-hosting/deployment/docker-compose).

## Start and stop

Desktop `npm start` and `npm run dev` automatically check both web and host-runner health
and invoke this launcher with `--no-browser` when unavailable. Docker must be
running. Healthy web and runner deployments are reused; desktop Quit leaves the stack and
its data running. See [desktop startup](../apps/desktop.md#desktop-workspace-tabs)
for failure recovery and startup timing.

Install Docker Engine and the Compose plugin, and ensure `docker info` works
for your user. From the repository root:

```bash
uv sync --locked --extra evals
uv run --extra evals chat-tft-evals up
uv run --extra evals chat-tft-evals down
```

The UI opens at <http://localhost:15510>. First startup downloads images, builds
the forwarding image, waits for schema migrations, seeds missing evaluation content
from the host interpreter, and starts the detached host experiment listener. Later startup preserves content edited in
Langfuse. `up --no-browser` starts the same services without opening a browser.

This is the canonical evaluation project. After the 2026-10-06 cutover, the
legacy `chattft-evals` stack on port 15500 is stopped with its volumes retained.
Its October 4 unit-expert result is preserved under the suite's ignored
`.migration/legacy-langfuse-cutover-20261006/` archive. New runs use the
`tft-apps-evals` project and this checkout's host runner. The historical run
was exported for review, not recreated as a native suite experiment.

Sign in with `LANGFUSE_INIT_USER_EMAIL` and `LANGFUSE_INIT_USER_PASSWORD`
from the generated `evals/langfuse/.env` file. The default email is
`evals@chattft.local`. The launcher creates random credentials once with
owner-only permissions and prints the configured email and password location,
never the password value. The suite desktop tab can use these fields for
automatic sign-in; see [suite desktop setup](../../../docs/desktop.md).
Do not replace this file while retaining the existing volumes: database
passwords, encryption keys, and API credentials must stay paired with their data.

Only the UI is published to loopback. Langfuse sends its authenticated webhook
requests to `http://experiments/experiments` on internal port 80. That container
forwards requests to the host through `.runtime/runner.sock`; no host TCP port
is opened. Existing dataset webhook URLs and credentials remain valid.

The host runner uses the invoking Python interpreter with the `evals` extra.
It reads model credentials and typed `RDS_EVAL_*` settings from the repository
`.env` and process environment. `127.0.0.1` now means the host, so a local
PostgreSQL listener works without changing database networking. Each evaluation
still runs in an isolated subprocess. The Unix socket is restricted to the host
user/group, and the proxy runs with the configured `HOST_UID`/`HOST_GID`.

`up` reuses a healthy owned runner. `down` stops it and Compose while retaining
history. After editing Python code or database settings, use:

```bash
uv run --extra evals chat-tft-evals restart-runner
```

Restart only when no experiment is running; interrupted work requires explicit
replay. Runner output is in `evals/langfuse/.runtime/runner.log`; PID ownership is
verified before shutdown. Docker proxy health includes host queue readiness.
Desktop exit leaves these services running; desktop startup recovers a stopped
runner. This local host lifecycle targets Linux, including WSL.

For a separate dependency environment without altering the app's virtualenv:

```bash
UV_PROJECT_ENVIRONMENT=evals/langfuse/.runtime/host-venv uv sync --locked --extra evals
```

The launcher uses that environment as a fallback when its selected interpreter
lacks Langfuse. This environment is ignored runtime state, not a backup artifact.

## Validation and troubleshooting

```bash
uv run --extra evals chat-tft-evals validate
uv run --extra evals chat-tft-evals run --suite dummy_assistant --offline
docker compose --env-file evals/langfuse/.env -f evals/langfuse/compose.yaml ps
docker compose --env-file evals/langfuse/.env -f evals/langfuse/compose.yaml logs --tail 100
```

Validation and the offline fixture need no Docker or model credentials. A missing
Docker executable, daemon permission failure, occupied port 15510, failed image
pull, or unhealthy migration stops startup with the underlying command error.
Stop any older service occupying the configured port before starting this stack.

If **via Webhook** reports HTTP 503, inspect `.runtime/runner.log` and the `experiments` forwarding service logs.
A healthy `/health` response only confirms the queue consumer is alive; content
preparation can still fail. After Python source changes, an `ImportError` may
indicate that the running process has cached an older module. Once no experiment
is running, reload it with:

```bash
uv run --extra evals chat-tft-evals restart-runner
```

Snapshot validation checks every entry in `snapshots/catalog.json`, so a missing
file for another suite can block a chat experiment too. Restore the exact missing
snapshot from backup when available. Otherwise, repair the affected catalog entry
to a verified available snapshot of that suite, recording the fallback; never
rename another snapshot to the missing hash or rewrite immutable snapshot content.
The data-analyst catalog entry was recovered to its available seven-case snapshot
`2d4a0cc0ca1ae81f895649df0e103900fe464e4d0a7ff49ffe94d8487bd5b9a6`
after the referenced `ead92fba85e7894e5cb17cbacbe87ce655d05b4bc61af0da4cd61540245c6d79`
file was found missing. Hosted dataset edits remain in Langfuse and are fetched
when preparing a new online experiment.

## Backup and restore

`down` preserves all named volumes. Back up the generated `.env`, exported
snapshots, `.runtime`, and the Compose volumes together. Stop the stack first so
PostgreSQL, ClickHouse, Redis, and object storage form a consistent local backup.
Docker volume names use the `tft-apps-evals_` prefix. Restore those volumes and the
same credentials before running `up` again. Do not use `down --volumes` unless
intentionally deleting platform history; Git snapshots restore definitions but
cannot restore results, annotations, or UI edit history.

The launcher captures the host Git revision and a content fingerprint covering
tracked differences plus untracked source content. The host runner can also read the checkout directly when recording per-job provenance.
The captured values remain available to container-based CI, where the external
Git directory may not be mounted. Restart through the launcher after editing code
to refresh this provenance. Running raw Compose commands without these values
records `unknown` rather than claiming a clean revision.

CLI `run` freezes the effective definition before execution, including
`--selection-live` and `--data-snapshot-label` when supplied. Online runs freeze current native cases and reviewed baseline prompt labels;
explicit snapshot replay retains the frozen inputs.
The resulting snapshot identifier appears in the JSON result. Unchanged offline
definitions reuse their existing content hash. Validation retains corpus
warnings, including references to removed skills.

An explicit CLI `run` executes the selected definition even when its catalog
entry came from the UI's export-only action. It records `action: run` in the
new effective snapshot. Runner-generated result links use the public
`LANGFUSE_PUBLIC_URL` (`http://localhost:15510`) rather than the Compose hostname.

## Upgrade an existing workspace

Before starting the new defaults, run the resumable [natural-contract migration](langfuse-content.md#export-migration-and-recovery). It exports the live workspace before renaming or converting any item. Startup refuses to seed a parallel natural dataset over an unmigrated legacy dataset. Preserve the private backup, rollback plan, journal, and volumes. The migration retains IDs and experiment links, archives obsolete skills, and removes the empty analysis trigger.

## Credential-free platform acceptance

Use a separate Compose project and fresh volumes for `LANGFUSE_TEST_DEPLOYMENT=1`. CI deliberately retains the isolated container runner: the launcher adds `compose.test.yaml`, routes application and native judge requests to `mock-model:8000`, seeds the internal fixture, and supplies an isolated typed `chattft_test` database target. `LANGFUSE_LLM_CONNECTION_WHITELISTED_HOST=mock-model` permits only that internal model host. This switch must not be applied to an existing real-model workspace.

The browser CI job exercises native item/prompt/evaluator editing, Custom Experiment variants and replay, real judge scheduling for all five profiles, development capture, and human annotations. It exports frozen definitions and complete workspace reports before stopping the temporary stack.

### Reloading the Playground adapter

The native Playground's **ChatTFT backend** connection is installed by normal
`chat-tft-evals up` seeding. After adapter code changes, run
`uv run --extra evals chat-tft-evals restart-runner` and restart the `experiments`
Compose proxy if its code changed. Existing installations also need
`chat-tft-evals up` to apply the internal LLM hostname allowlist and seed the new
connection. Prompt edits in Playground require neither restart. See the
[edit/run/inspect walkthrough](langfuse-onboarding.md#edit--run--inspect-in-playground).
