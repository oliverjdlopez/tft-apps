"""Execute a reviewed authored baseline with a fresh captured assistant graph."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from evals.assistant_execution import current_execution
from evals.baselines import ROOT, validate_baselines
from evals.langfuse import launcher
from evals.langfuse.content import export_snapshot, load_snapshot


def run(suite, data_snapshot_label=None):
    """Capture current code while retaining the explicitly reviewed case contracts."""
    baselines = validate_baselines()
    if suite not in baselines:
        raise ValueError(f"Unknown authored baseline: {suite}")
    bundle = load_snapshot(baselines[suite], ROOT / "langfuse/snapshots")
    bundle["execution"] = current_execution(bundle["suite"], bundle["config"]["variants"])
    with TemporaryDirectory(prefix="baseline-run-") as temporary:
        previous = launcher.SNAPSHOT_ROOT
        try:
            launcher.SNAPSHOT_ROOT = Path(temporary)
            snapshot = export_snapshot(bundle, launcher.SNAPSHOT_ROOT)
            return launcher.run(suite, snapshot=snapshot, data_snapshot_label=data_snapshot_label)
        finally:
            launcher.SNAPSHOT_ROOT = previous


def main():
    """Run a baseline only when this separate, explicitly paid command is invoked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suite")
    parser.add_argument("--data-snapshot-label", required=True)
    args = parser.parse_args()
    return run(args.suite, args.data_snapshot_label)


if __name__ == "__main__":
    raise SystemExit(main())
