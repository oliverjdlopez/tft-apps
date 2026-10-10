# Managing assistant specs

Use `uv run chat-tft-specs` to create and retire repository assistants. The
equivalent command without refreshing installed entrypoints is
`.venv/bin/python -m scripts.assistant_specs`. Neither command runs a model.

Edit and test existing assistants in the [Specs workspace](assistant-workspace.md).
Save draft never changes application behavior; Apply validates and installs it.

## Create or copy

Write the intended system instructions in a text file, then run:

```bash
uv run chat-tft-specs list
uv run chat-tft-specs create new_expert --prompt-file /path/to/system.md
uv run chat-tft-specs create new_expert --copy-from unit_expert
```

Choose one creation command. You can combine `--copy-from` and `--prompt-file`
to retain the source configuration while replacing its instructions. Creation
never overwrites an existing directory or registered name. It validates the new
spec's tool references and handoffs before publishing the complete directory.
New names use lowercase letters, digits, and underscores and start with a letter.

A fresh spec starts with no tools, skills, handoffs, or repository context.
Copies retain the source's access and optional task wrapper. Review copied
instructions for references to the old assistant's name. Configure access in
`app/backend/src/domain/assistant_specs/<name>/agent.json` and edit instructions
in `system.md`; the application's Developer → Specs page can edit these files too.
Creating a spec does not create an empty evaluation dataset.

## Retire an assistant

```bash
uv run chat-tft-specs remove old_expert
uv run chat-tft-specs remove old_expert --apply --backup-dir /path/to/spec-backups
```

The first command reports the source path and dependencies without changing
anything. The second recomputes that report and refuses removal while blockers
remain. Checks cover incoming handoffs, exact Python string references in backend
and script sources, active eval suite targets, prompt candidates, and deterministic
checks. Python comments do not block removal. Source checks are conservative:
constants and other exact string uses may require manual review. They cannot
prove the absence of dynamically constructed references or external clients.

Migrate callers and handoffs to the replacement first. For a retired eval suite,
review its Langfuse dataset and remove its entry from
`evals/langfuse/snapshots/catalog.json`; export changed suites through the normal
snapshot workflow. Keep old hash-named snapshots unchanged. Dataset deletion and
shared evaluator changes remain explicit workspace maintenance operations; this
command does not remove datasets or experiment history.

Applying removal moves the **entire spec directory**, including any additional
files, to a unique directory under `--backup-dir` and reports its location. Restore
that directory to its original path to undo the local removal, provided the name
has not since been reused. Backups must be outside the assistant-spec directory.
The command rejects specs containing symlinks.

## Create missing Langfuse prompts

```bash
uv run --extra evals chat-tft-specs sync-langfuse
uv run --extra evals chat-tft-specs sync-langfuse --apply
uv run --extra evals chat-tft-specs sync-langfuse --remove old_expert
uv run --extra evals chat-tft-specs sync-langfuse --remove old_expert --apply --backup-dir /path/to/spec-backups
```

Synchronization reads the configured Langfuse workspace and previews changes by
default. Applying creates missing `chattft/assistants/<name>` text prompts with
the `baseline` label. Existing prompt versions, labels, and UI edits are preserved;
editing a repository spec does not silently promote it to a Langfuse baseline.

`--remove` names each retired assistant explicitly and can be repeated. Its local
spec must already be absent, with no remaining source or active eval dependencies.
Deletion backs up every hosted version, its configuration, and labels in a private
`langfuse-prompts-*/prompts.json` directory before changing the platform. References
from any retained prompt version block deletion. Each version is rechecked and
deleted individually, so an intervening new version is never deleted implicitly.
The accompanying `journal.json` records completed operations even after a partial
failure. Re-run a preview to reconcile before retrying. These backups preserve
definitions for manual recovery, not original hosted version IDs or history links.

Only the requested assistant prompts are deleted. Other prompts, datasets,
evaluators, traces, and experiment results are untouched. Local and hosted changes
are separate steps: a stopped Langfuse workspace cannot roll back a local removal.
Sync failures exit nonzero and can be retried once connectivity is restored.

Normal Langfuse startup also creates missing prompts from current repository specs.
This CLI creates missing authored prompts; it does not synchronize existing edits
and is not part of ordinary editing. Fresh assistant experiments capture current
repository definitions and publish concrete managed prompt versions. Removing an unrelated prompt
therefore neither breaks those experiments nor causes startup to recreate it.
Frozen replay continues to use its recorded definitions and still requires the
corresponding executable assistant code.

## Reload and validate

After terminal edits, use **Refresh active definitions** in Specs to validate
the complete graph and refresh its cached registry, or restart the backend. In Electron, **View → Force Reload** (`Ctrl+Shift+R`) restarts the backend;
this interrupts in-flight work. Refresh a browser page after restarting its backend.
To refresh Langfuse's configured Playground model list and its experiment service:

```bash
uv run --extra evals python -m evals up --no-browser
uv run --extra evals python -m evals restart-runner
uv run pytest -q tests/test_assistants.py tests/test_assistant_spec_management.py
uv run --extra evals python -m evals validate
```

Review graph-sensitive tests and docs for the specific assistant change. Existing
catalog/selector failures can be independent of a spec change; inspect the named
failure before changing expectations. New assistants can be exercised in Playground;
add a meaningful dataset and suite only when there is behavior to evaluate.
