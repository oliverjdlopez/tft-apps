# Migration verification

## Media sharing follow-up

The subsequent media-sharing implementation passed 56 desktop Node tests,
41 focused ChatTFT/desktop Python tests, and 58 focused VOD Python tests.
The Python checks include bidirectional resource HTTP transfers in independently
installed interpreters, shared video/audio download reuse, default directory
agreement, actual video validation, corruption/missing-file handling, upload
cleanup, review deletion, scheduler regressions, and launcher ownership.
The vendored protocol copies match; local documentation links and
`git diff --check` passed. Tests used temporary media/databases and generated
local video/audio; no live downloads, GPU inference, application RDS access,
or paid evaluations were run. HTTP/launcher checks needed local socket access
outside the restricted sandbox. The desktop test suite also built ChatTFT's
frontend. Existing source checkout statuses were preserved. No new GUI flow
or real Windows/WSL launch was exercised for this follow-up. These focused
results do not replace the historical full-suite limitations below.

## Original migration

The imported baseline comes from ChatTFT `dev` at
`d5cf526a3d581c9ffb328d77c913d29d7d0c4d46` and VOD `dev` at
`ffecf47327025accee6448c1aacb9cd5ac37c8fd`. Both original statuses were checked
before copying and during final inventory verification. No source checkout edits,
source service shutdowns, source runner changes or original Docker volume reuse
were performed. Remote RDS data was neither copied nor rebuilt.

## File and authored-content checks

- 1,376 files copied independently, with SHA-256 and inode comparisons.
- All 382 VOD dataset files retained; only two `data.yaml` absolute roots changed.
- All 58 evaluation snapshot/catalog files retain their original bytes. Git marks
  snapshot JSON as text-disabled so future checkout does not alter hashes.
  The final byte-preservation commit corrects Git's import-time index normalization;
  working files stayed unchanged. Its apparent snapshot diffs contain only line
  endings, and all committed blobs were compared with the original SHA-256 hashes.
- Ordinary `agent_configs` files retained; submodule metadata omitted.
- Evaluation export/import: 6 datasets, 56 cases, including 11 archived cases,
  23 prompt versions, 5 current evaluators and 5 rules. No source resources were
  unavailable. Repeated import retained the same case counts and exact authored
  inputs, expected outputs, metadata, schemas and archived status. Prompt content
  and labels, current evaluator definitions/status and remapped rules were checked.
- Historical evaluator versions remain in the private export; the fresh platform
  uses current definitions. Source traces, scores, experiments and run history
  were excluded. No model calls were made during import or setup.
- Source private settings are ignored copies; destination tracing keys and runtime
  paths are isolated. Credentials and copied bulk datasets remain untracked.

Private audit artifacts and logs are in `.migration/`; the [manifest](migration-manifest.json)
records identities, exclusions and counts. `python3 scripts/verify_migration.py`
rechecks source bytes/status, dataset inventory, snapshot preservation, independent
copies, fresh runtime storage, and lists every intentional destination file edit.

## Executed validation

| Check | Result |
| --- | --- |
| Desktop Node lifecycle/path tests | 56 passed |
| Desktop Python ownership tests | 12 passed |
| ChatTFT frontend | 108 tests passed; production build passed |
| VOD frontend | 43 tests passed, 1 existing test failed; production build passed |
| VOD Python with importlib collection | 185 passed |
| ChatTFT Python full collection | 2 existing import blockers |
| ChatTFT runnable suite with isolated PostgreSQL | 807 passed, 28 failed, 8 skipped |
| Comparison of the 28 failures with imported baseline | All 28 reproduced; no migration-only failed node IDs |
| Offline dummy assistant evaluation | Passed with disposable snapshot directory |
| Full offline evaluation validation | Existing provider compatibility import failure |
| Native Electron workspace fixture | Passed navigation, IPC isolation, retained state, offline/retry and cleanup |
| Real Electron/WSLg application smoke | All six product views loaded on disposable ports; owned processes stopped on close |
| Normal-port startup smoke | Rejected occupied port 8000 without adopting/stopping its service |
| WSL automated checks | Passed root/path, distribution/user, private env/cwd forwarding, identity and pipe shutdown |
| Native Windows-to-WSL bridge | Both production/dev modes, parent EOF, abrupt wrapper loss and occupied-port rejection passed |
| Native Windows Electron fixture | IPC isolation, retained views, offline/retry and cleanup passed with a disposable profile |
| CloudBeaver | Separate project/volume and 8979→8978 mapping checked; explicit startup retained |

The ChatTFT collection blockers are missing `assistant_reachable_names` and
`_selected_skill_ids` exports. Broader failures include stale evaluation inventory
expectations, outdated monkeypatch paths/signatures, composition tests and a
pre-existing runtime import cycle. The exact node IDs are in private test logs;
a separately extracted imported-baseline copy reproduced the same 28 failures
under the same isolated database environment. Some ingestion tests fail before
any action because their outdated mocks fall through to the deliberately absent
application database; validation never pointed those operations at RDS.
The VOD frontend failure is `App.test.tsx`'s paused-download dismissal assertion;
its application/test files are byte-identical to the imported source. Plain VOD
pytest collection also has duplicate `test_inference`, `test_model` and
`test_train` module names; `--import-mode=importlib` avoids that existing collision
and is used by suite CI.

Original services occupy ports 8300, 8000 and 5174. It was left running. The real smoke used
its opt-in ephemeral ports and a disposable destination VOD directory; normal
desktop defaults remain unchanged and require free ports. RDS was disabled for
renderer smoke, so database-backed product actions were not exercised. A fresh Windows Electron cache was installed successfully with
`npm run setup:wsl` under the independent `tft-apps` application-data identity.
Native Windows Electron fixture behavior and the real Windows-to-WSL bridge
passed. The six real product renderers were tested under Linux Electron/WSLg;
full Windows product GUI behavior remains unverified. No ingestion, projection
rebuild, paid eval run, production mutation, push or publication was performed.

Fresh Langfuse and its destination-local host runner remain available at
`http://localhost:15510`. CloudBeaver has a separate fresh workspace; start it
explicitly with `docker compose -f desktop/cloudbeaver/compose.yaml up -d` from
the suite root. The disposable PostgreSQL test container was stopped after checks.
