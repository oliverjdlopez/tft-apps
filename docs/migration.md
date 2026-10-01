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
