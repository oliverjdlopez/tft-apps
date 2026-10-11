# Migration contract and audit

The [manifest](migration-manifest.json) records source dev commits, working-tree
status and copy counts. The private `.migration/inventory.json` inventories every
copied file with original path, destination, size and SHA-256, plus excluded paths.
Independent copies were hash-checked and compared by inode; no writable links or
hardlinks reach source files. `agent_configs/` is ordinary source, with no
submodule declaration. The first commit is the imported source baseline;
subsequent commits contain intentional suite changes.

Ignored evaluation inputs, fixtures, local case drafts and immutable snapshot
bytes were retained. VOD's complete `data/datasets` tree is copied, including
training splits and augment templates, with its original ignore behavior. Only
absolute dataset YAML roots change. Necessary local model weights and templates
are copied; model download locks/caches are excluded. Source trace data, runtime
SQLite databases, task state, videos, downloads, playback assets, OCR/frame caches,
profiles, build output and dependency directories are excluded. New runtime
storage belongs to the destination. No external RDS data is copied or rebuilt.
Private settings remain ignored; external credential file references are retained.
The initial migration deferred shared media. The suite now owns a fresh shared
media catalogue and ResourceStore; original runtime storage remains untouched.
See [media sharing](shared-media.md). A shared installed Python package remains
deferred; both applications retain independent vendored protocol implementations.

`python3 scripts/migrate_evals.py export` exports all live source datasets/items,
including archived status, prompt versions, evaluator definitions and evaluation
rules through read-only content APIs. Authentication creates only a login session.
It excludes experiments, trace history and scores. Exports are private ignored
files under `.migration/`. `import` targets only localhost:15510 and uses stable
case IDs and semantic content comparisons to make reruns idempotent. Required
resource IDs in rules are remapped; unavailable definitions are reported explicitly.
`verify` checks imported counts, statuses, dataset schemas, prompt version bytes
and labels, current evaluator definitions and remapped rule content against the export.
Do not run this importer against an original instance. Restore authored content
before normal seeding so local snapshots do not replace live case edits.

Run `python3 scripts/verify_migration.py` to compare source status and inventory,
report all intentional destination edits, prove snapshot byte preservation,
verify the full VOD dataset inventory and detect original runtime state. Validation
results and limitations are recorded in [verification](verification.md).

The export retains historical evaluator versions for audit; the fresh platform
uses each current authored evaluator definition. Source provider secret keys
are never exported through platform APIs. The normal destination setup installs
its backend connection and the copied application OpenAI credential without
making model calls.

On 2026-10-01, the user requested copying the populated unit expert dataset into
this suite and running it here. The existing `chattft/unit-expert` dataset kept
its destination ID and received all 17 active cases from the source
`unit-expert` dataset. Inputs, expected outputs, metadata, statuses and all 51
deterministic checks were verified against a fresh source export. The local
suite definition retains the source's 40-turn limit and `unit_expert` assistant;
the destination's baseline prompts and native grading configuration remain in
use. The private export, prior destination definition, item-ID mapping and run
receipt are under ignored `.migration/unit-expert-20261001/`. Source services
were accessed only to read dataset content; execution uses this suite's runner
and Langfuse project on port 15510.

On 2026-10-06, the remaining expert workflow was consolidated into this suite.
The live `chattft-evals` definitions were exported before mutation, then all 69
active item, unit, composition and trait cases were verified field by field in
the `tft-apps-evals` project. The existing unit and item dataset IDs were kept;
composition and trait datasets were added. Their current case versions and
40-turn routing are recorded in the active snapshot catalogue. The empty meta
dataset remains available. The legacy `chattft-evals` Compose stack was stopped
without deleting its volumes. Its 30 terminal local jobs were archived, and the
suite host runner now uses a fresh queue. Its experiment buttons and webhook
health were verified at <http://localhost:15510>. Private source, destination, job,
and verification records are under ignored
`.migration/legacy-langfuse-cutover-20261006/`.

The 2026-10-04 legacy unit-expert experiment is preserved there as a complete
job record and a prompt/final-output Markdown export. Langfuse run identities,
traces and scores were not transplanted into the suite project; its old UI link
will be unavailable while the legacy stack is stopped. The preserved legacy
volumes are a recovery copy, not an execution target. Future experiments belong
to the suite project on port 15510.

On 2026-10-08, the latest preserved unit-expert run (2026-10-04,
`adea170a7b476b85`) was re-exported without rerunning it. The prompt/final-output
Markdown and verification receipt are under ignored
`.migration/unit-expert-export-20261008/`. All 17 frozen inputs and complete
responses match the archived job record; the inputs use the shorter player
questions without the October 1 run's appended analysis instructions. All 17
executions returned answers, with 12 grading passes and 5 grading failures.
The export omits traces, tool calls, and grading commentary.

The preserved `chattft-evals_minio` volume was subsequently inspected read-only.
All 17 October 4 root observations retain `metadata.tft_trace`, including 181
tool calls with JSON arguments. Their inputs and outputs match the archived
job record. The recovered captures are saved separately as
`.migration/unit-expert-export-20261008/recovered-tool-traces.json`, with a
readable `UN4-1-C01-tool-arguments.md` example alongside it. These captures
include resolver outputs but omit other tool returns and per-call timing;
they are not complete observation exports. No legacy services were restarted.

The combined
`.migration/unit-expert-export-20261008/2026-10-04-unit-expert-prompts-outputs-and-tool-arguments.md`
retains all 17 prompts and final responses, followed in each case by its tool
calls in recorded order. All 181 calls have arguments rendered as Markdown
lists, including nested fields and explicit nulls; tool return values are
excluded. The adjacent `tool-arguments-artifact-verification.json` records the
artifact hash and verified counts.

The 2026-10-02 preservation of the older `tft-suite` checkout retains its
remaining authored evaluation files, immutable snapshots and complete Git
history without replacing this suite's active catalogue. See the
[retirement record](retiring-tft-suite.md) for archive locations, worktree
handling, recovery and the current relocation status.
