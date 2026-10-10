# Local Langfuse deployment

The evaluation platform lives under `evals/langfuse/`. Docker Compose runs
Langfuse web/worker, PostgreSQL, ClickHouse, Redis, MinIO and the real Python
experiment server. The experiment server shares the ChatTFT application image;
its tools and per-run subprocesses execute inside the container. External RDS
and hosted model providers retain their existing roles.

## Start and stop

From the suite root, build images with `node desktop/docker.mjs build`, then use:

```bash
node desktop/docker.mjs langfuse-up
node desktop/docker.mjs eval-restart
node desktop/docker.mjs eval-down
```

Desktop startup checks both the web service and the actual container runner's
command, health and project ownership. It starts missing services through the
Node launcher. Desktop quit leaves Langfuse running. The legacy Python CLI
`chat-tft-evals up/down/restart-runner` delegates to the same Node lifecycle.

The UI remains at <http://localhost:15510>. The existing `tft-apps-evals`
project, volumes, generated `.env` keys, hosted content, snapshots and job
artifacts are retained. Keys are created only when absent; never replace them
while retaining existing encrypted data. Credentials stay outside images and
renderer JavaScript. Setup seeds missing definitions without making model calls.

Only the UI is published. Existing authenticated webhooks target
`http://experiments/experiments` on internal port 80. That service now executes
the request directly. It reads complete typed `RDS_EVAL_*` settings and model
credentials from the application `.env` plus process overrides, and uses the
internal Langfuse hostname. Result links retain the public localhost URL.
A host-only database/tunnel needs a container-reachable address; `localhost`
inside the container refers to that container. No external RDS data is migrated.

The migration checks the persistent queue read-only before changing ownership.
Queued, running or awaiting-score jobs block migration/restart/shutdown. It
stops ingress, checks again, and retires only a verified legacy host process
whose command owns this suite's exact socket. A live process hidden by a PID
namespace blocks migration instead of starting a second consumer. The queue and
artifacts stay under `.runtime/`. No new paid run is submitted.

`node desktop/docker.mjs eval-compose logs --tail 100 experiments` shows runner
logs. Use `eval-restart` after Python source/config edits and rebuild the shared
image after dependency changes. Desktop restarts recover stopped containers.
The earlier `chattft-evals` project remains retired with its historical volumes
and exports preserved. See [suite Docker lifecycle](../../../docs/docker-desktop.md).

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
Stop an older Promptfoo viewer before starting this stack on the same port.

If **via Webhook** reports HTTP 503, inspect the `experiments` container logs.
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
tracked differences plus untracked source content. The captured values are passed to the container for per-job provenance.
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
`uv run --extra evals chat-tft-evals restart-runner`. Existing installations also need
`chat-tft-evals up` to apply the internal LLM hostname allowlist and seed the new
connection. Prompt edits in Playground require neither restart. See the
[edit/run/inspect walkthrough](langfuse-onboarding.md#edit--run--inspect-in-playground).
