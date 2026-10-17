"""Execute the pinned offline fixture without changing the tracked catalog."""

from tempfile import TemporaryDirectory
from pathlib import Path

from evals.baselines import ROOT, validate_baselines
from evals.langfuse import launcher
from evals.langfuse.content import export_snapshot, load_snapshot


def main():
    """Copy fixture content to disposable storage before running the real CLI path."""
    snapshot = validate_baselines()["dummy_assistant"]
    bundle = load_snapshot(snapshot, ROOT / "langfuse/snapshots")
    with TemporaryDirectory(prefix="eval-fixture-") as temporary:
        launcher.SNAPSHOT_ROOT = Path(temporary)
        export_snapshot(bundle, launcher.SNAPSHOT_ROOT)
        return launcher.run("dummy_assistant", snapshot=snapshot, offline=True)


if __name__ == "__main__":
    raise SystemExit(main())
