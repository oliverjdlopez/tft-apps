"""Verify source invariants, copied inputs and intentional destination changes."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Compare migration inventories and reject source or immutable-input changes."""
    manifest = json.loads((ROOT / "docs/migration-manifest.json").read_text())
    inventory = json.loads((ROOT / ".migration/inventory.json").read_text())
    sources = {Path(source["root"]).name: Path(source["root"]) for source in manifest["sources"]}
    edits = []
    for source in manifest["sources"]:
        args = ["git", "-C", source["root"]]
        environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
        for command, expected in [("status", source["status"]), ("rev-parse", source["commit"] + "\n")]:
            flags = ["--porcelain=v1"] if command == "status" else ["HEAD"]
            actual = subprocess.check_output([*args, command, *flags], env=environment, text=True)
            if actual != expected:
                raise ValueError(f"Source identity changed: {source['root']} {command}")
    dataset_count = 0
    snapshots = 0
    for entry in inventory["files"]:
        source = sources[entry["source"]] / entry["path"]
        destination = ROOT / (".github/workflows/ci.yml" if entry["destination"] == "tft-chat/.github/workflows/ci.yml" else entry["destination"])
        with source.open("rb") as stream:
            source_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        if source_hash != entry["sha256"]:
            raise ValueError(f"Source bytes changed: {source}")
        if destination.is_symlink() or source.stat().st_ino == destination.stat().st_ino:
            raise ValueError(f"Copy is not independent: {destination}")
        with destination.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        changed = digest != entry["sha256"]
        if changed:
            edits.append(entry["destination"])
        if "evals/langfuse/snapshots/" in entry["path"]:
            snapshots += 1
            if changed:
                raise ValueError(f"Immutable snapshot changed: {destination}")
            committed = subprocess.check_output(["git", "show", "HEAD:" + entry["destination"]], cwd=ROOT)
            if hashlib.sha256(committed).hexdigest() != entry["sha256"]:
                raise ValueError(f"Committed snapshot bytes differ: {destination}")
        if entry["source"] == "vod-review" and entry["path"].startswith("data/datasets/"):
            dataset_count += 1
            if changed and destination.name != "data.yaml":
                raise ValueError(f"Dataset bytes changed: {destination}")
    expected = {entry["path"] for entry in inventory["files"] if entry["source"] == "vod-review" and entry["path"].startswith("data/datasets/")}
    actual = {str(path.relative_to(sources["vod-review"])) for path in (sources["vod-review"] / "data/datasets").rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("VOD dataset copy inventory is incomplete")
    for app in ["vod-review", "tft-chat"]:
        data = ROOT / app / "data"
        databases = list(data.glob("*.sqlite*")) + list(data.glob("*.db"))
        if databases:
            raise ValueError("Destination contains a non-disposable application database")
        for name in ["videos", "downloads", "playback", "frame_cache", "ocr_cache", "traces"]:
            directory = data / name
            if directory.exists() and any(directory.iterdir()):
                raise ValueError(f"Original runtime state may be present: {directory}")
    baseline = subprocess.check_output(["git", "rev-list", "--max-parents=0", "HEAD"], cwd=ROOT, text=True).strip()
    changes = subprocess.check_output(["git", "diff", "--name-status", baseline], cwd=ROOT, text=True).splitlines()
    introduced = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True).splitlines()
    report = {"reviewable_changes": changes + ["A\t" + name for name in introduced], "source_identities_unchanged": True, "copied_files": len(inventory["files"]),
        "immutable_snapshot_files": snapshots, "committed_snapshot_bytes_match": True, "vod_dataset_files": dataset_count,
        "intentional_destination_edits": sorted(edits), "runtime_storage_fresh": True}
    (ROOT / ".migration/verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in {"intentional_destination_edits", "reviewable_changes"}}))


if __name__ == "__main__":
    main()
