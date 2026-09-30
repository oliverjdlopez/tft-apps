# Native Promptfoo compatibility history

> Historical record: Promptfoo has been replaced by Langfuse. Commands and source
> paths below describe the retired implementation and are not current setup
> instructions. See [Tests and evaluations](testing-and-evals.md) for the active
> platform and snapshot workflow. Existing Promptfoo history remains untouched.

## Decision at the time

The repetition-count issue no longer blocks the migration. ChatTFT has dropped
its expected-attempt count, minimum-pass-rate aggregation, and custom fail-fast
policy. Promptfoo owns execution, grading, reports, and exit status. Native
repetition remains available but ChatTFT does not configure or validate it.

`evals/runner.mjs` and `evals/aggregate.mjs` have been removed. The launcher only
prepares optional repository presets before invoking the native CLI. Python
adapters retain application execution, tool/selector assertions, trace evidence,
and operation timeouts. Native CLI/UI calls need no launcher-created locks.
See [Tests and evaluations](testing-and-evals.md) for the resulting workflow.

## What the earlier blocker meant

On 2026-09-12, the probe against pinned Promptfoo 0.123.0 requested three
attempts through the native UI job backend. All three ran, but the configuration
exposed to `afterAll` omitted `evaluateOptions.repeat`. Resubmitting that
configuration ran once. Basic CLI/UI execution and hooks already passed.

The old ChatTFT checker required the original requested count independently of
the completed results. Otherwise, one successful result from an incomplete
three-attempt experiment could look like a successful one-attempt experiment.
The previous migration therefore stopped rather than retaining a custom source
of repetition settings or patching Promptfoo internals.

That was a conflict with our old acceptance policy, not an inability to execute
or grade tests in Promptfoo. Removing that policy removes the prerequisite; it
does not fix or claim to fix upstream repeat-setting persistence.

## Historical verification

After `uv sync --locked` and `npm ci --prefix evals/promptfoo`, run:

```bash
PROMPTFOO_PYTHON="$(uv run --no-sync python -c 'import sys; print(sys.executable)')" node evals/promptfoo/tests/native-compatibility.probe.mjs
```

The probe uses temporary storage and no model credentials or database. It starts
a temporary viewer (port 15572, overridden by `TFT_NATIVE_PROBE_PORT`), verifies
native CLI/UI hooks, then executes the real ChatTFT fixture with its five domain
assertions through the CLI, UI job backend, and saved-config rerun. It stops the
viewer and removes its temporary files. Repeat-setting observations are printed
for diagnosis and are no longer acceptance gates. CI runs this probe.

This verifies the viewer's execution backend rather than browser interactions.
Paid live runs are not needed for this deterministic check. Native filtering,
provider comparisons, exports, failure exit status, rubric thresholds, and
selector assertion failures are covered by the Node adapter tests. The Python
tests cover real graph assembly with fakes, scoped database targets, direct
provider execution, inventory, and operation timeouts.

## Checkout validation on 2026-09-13

- Repository schema/domain preflight: eight suites and 54 cases validated.
- Node adapter/integration tests: eight passed, including native provider
  filtering, JSON export, failure exit status, and selector grading.
- Python adapter tests: 11 passed.
- Native CLI/UI fixture and saved-config rerun probe: passed on Promptfoo 0.123.0.
- Full offline evaluation: 20 passed, the same four documented context cases
  failed, and zero execution errors; native exit status was 100.
- Full pytest: stopped during collection at the pre-existing missing
  `assistant_reachable_names` import in `tests/test_assistant_access.py`.

Validation used Node 23.11.0 and Python 3.14.5 from the existing local environment;
CI remains configured for Node 22. Paid live evaluation was not run. Existing
checkout history was not changed by validation.
