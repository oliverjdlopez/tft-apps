# Retiring the older tft-suite checkout

`tft-apps` is the working suite. On 2026-10-02, the old `~/tft-suite` directory
was moved into the private archive below after its Claude session exited.
The old top-level directory is absent. Its complete contents remain recoverable.

## Preserved application work

The missing `tft-chat/eval-brainstormings/2026-09-30-code-grounded/` tree contains
92 byte-identical authored files, including all 69 Set 18 cases, expert
allocations, authoring scripts and historical validation receipts. The expert
definitions contain 18 composition, 17 item, 17 trait and 17 unit cases, with all
154 deterministic checks. Inputs, expected outputs, statuses and case identities
match the combined authoring dataset. The specialist allocations retain their
documented metadata and tool-alternative adjustments.

Sixteen additional immutable snapshots were copied into
`tft-chat/evals/langfuse/snapshots/`. The old catalogue is retained separately at
`tft-chat/evals/langfuse/archives/tft-suite-20261002/catalog.json`. Its snapshot
identifiers resolve in the normal snapshot directory; the archive directory is
an inventory, not a standalone `LANGFUSE_SNAPSHOT_DIR`.

The current catalogue, existing unit expert import and local uncommitted work
are preserved. Copying these definitions does not register cases in the running
Langfuse instance. The old authored files and receipts describe their original
source workspace; their live dataset IDs, absolute paths and historical success
claims are not current verification of this suite. No model evaluation,
ingestion, projection rebuild or database mutation is part of this retirement.

## Private archive and recovery

The ignored, private archive is
`.migration/retired-tft-suite-20261002/`. It contains:

- `history.git`: an independent copy of the complete original Git database,
  retaining reflogs and all objects. Detached worktree commits have additional
  `refs/archive/worktrees/*` anchors in this backup only.
- `history.bundle`: a self-contained bundle of every original ref and the
  detached-worktree anchors. It was restored into `bundle-restore.git` and passed
  Git object connectivity checks.
- `before.json`: the original 54 refs, source identity, worktree/backlink inventory
  and the working suite's initial status.
- `apps-existing-changes.patch`: a backup of the suite's pre-existing tracked
  changes, including its current catalogue.
- Evaluation copy hashes and verification reports.
- `checkout/`: the entire old directory, including its
  credentials, ignored data, benchmark artifacts, runtime files, installed
  dependencies and Git metadata.

Relocation uses a same-filesystem rename, preserving every file and inode.
Surviving linked worktrees are repaired to the archived checkout's Git database;
their branches, staged/unstaged changes and untracked-file status are checked
before and after. Missing worktree registrations are retained rather than pruned.
The application does not start or adopt services from this archived checkout.
Absolute paths in archived settings and dependency scripts remain historical.

This is conservation of work, not disk-space cleanup: no old artifacts or
dependencies are discarded. Keep the archive private and ignored because it
contains secrets and runtime data. Do not upload the complete archive or resume
the old services as part of normal suite operation.

For independent Git recovery, clone `history.bundle` into a new directory.
It contains the 41 original local branches, remote-tracking refs, and detached
commit anchors. File-only artifacts, reflogs and uncommitted/ignored work require
the full checkout or Git database, rather than the bundle alone.

The `retirement-verification.json` receipt confirms all 54 original refs and
the complete directory were retained. All 11 surviving worktrees now resolve
to the archived Git database, with identical staged/unstaged changes and
untracked-file status. Their existing branches and detached HEADs remain intact.
The two idle terminal shells were left running; their cwd inodes followed the
rename, although their `$PWD` variables may still display the former path.

Verification also restored the independent bundle and checked Git object
connectivity, compared all 109 copied files by SHA-256, checked 69 unique expert
cases and 154 checks, validated the 16 copied snapshots through the current
snapshot loader, and validated both catalogues (12 current and 14 historical
suites). The active catalogue's bytes were checked before and after relocation.
Application suites, real model evaluations and hosted dataset writes were not
run because this change preserves files and Git links rather than changing the
application runtime.

This record supplements the original [migration audit](migration.md); it does
not rewrite that historical manifest or transplant the old runtime state into
either active application.
