"""Local Langfuse platform lifecycle and snapshot evaluation commands."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import webbrowser
from domain.assistants.constants import AssistantName

PLATFORM_ROOT = Path(__file__).resolve().parent
SNAPSHOT_ROOT = Path(os.environ.get("LANGFUSE_SNAPSHOT_DIR", str(PLATFORM_ROOT / "snapshots")))
PUBLIC_URL = "http://localhost:15510"


def prepare_environment(root: Path = PLATFORM_ROOT) -> Path:
    """Create private local credentials once for the persistent Compose stack.

    Args:
        root: Directory containing the Compose definition.

    Returns:
        Path to the existing or newly created private environment file.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / ".runtime").mkdir(exist_ok=True)
    (root / "snapshots").mkdir(exist_ok=True)
    path = root / ".env"
    if path.exists():
        return path
    values = {name: secrets.token_hex(32) for name in (
        "POSTGRES_PASSWORD", "CLICKHOUSE_PASSWORD", "REDIS_AUTH",
        "MINIO_ROOT_PASSWORD", "SALT", "NEXTAUTH_SECRET", "ENCRYPTION_KEY",
        "LANGFUSE_EXPERIMENT_TOKEN", "LANGFUSE_INIT_USER_PASSWORD",
    )}
    values.update({
        "LANGFUSE_PUBLIC_KEY": "pk-lf-" + secrets.token_hex(16),
        "LANGFUSE_SECRET_KEY": "sk-lf-" + secrets.token_hex(32),
        "LANGFUSE_INIT_USER_EMAIL": "evals@chattft.local",
        "HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid()),
    })
    # Exclusive creation protects keys already paired with persistent volumes.
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return path
    with os.fdopen(descriptor, "w") as stream:
        stream.write("".join(f"{key}={value}\n" for key, value in values.items()))
    return path


def capture_provenance(root: Path = PLATFORM_ROOT.parent.parent) -> dict[str, str]:
    """Capture source identity on the host where worktree Git metadata exists.

    Args:
        root: Repository worktree to identify before container execution.

    Returns:
        Revision and content fingerprint environment variables for the runner.
    """
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL).decode().strip()
        difference = subprocess.check_output(["git", "diff", "HEAD", "--binary"], cwd=root, stderr=subprocess.DEVNULL)
        untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=root, stderr=subprocess.DEVNULL)
        fingerprint = hashlib.sha256(difference)
        for name in sorted(filter(None, untracked.split(b"\0"))):
            source = root / os.fsdecode(name)
            fingerprint.update(name + b"\0")
            if source.is_symlink():
                fingerprint.update(hashlib.sha256(os.readlink(source).encode()).digest())
            elif source.is_file():
                fingerprint.update(hashlib.sha256(source.read_bytes()).digest())
        return {"CHAT_TFT_GIT_REVISION": revision,
                "CHAT_TFT_WORKING_TREE_FINGERPRINT": fingerprint.hexdigest()}
    except (OSError, subprocess.CalledProcessError):
        return {"CHAT_TFT_GIT_REVISION": "unknown",
                "CHAT_TFT_WORKING_TREE_FINGERPRINT": "unknown"}


def compose(arguments: list[str], root: Path = PLATFORM_ROOT) -> None:
    """Execute Compose with explicit project and credential paths.

    Args:
        arguments: Compose subcommand and options.
        root: Directory containing the platform configuration.
    """
    environment = os.environ.copy()
    environment.update(capture_provenance(root.parent.parent))
    if environment.get("LANGFUSE_TEST_DEPLOYMENT") == "1":
        environment["LANGFUSE_LLM_CONNECTION_WHITELISTED_HOST"] = "mock-model"
    subprocess.run([
        "docker", "compose", "--project-name", "tft-apps-evals", "--project-directory", str(root),
        "--env-file", str(root / ".env"), "-f", str(root / "compose.yaml"),
        *(["-f", str(root / "compose.test.yaml")] if environment.get("LANGFUSE_TEST_DEPLOYMENT") == "1" else []),
        *arguments,
    ], check=True, env=environment)


def up(*, open_browser: bool = True) -> None:
    """Start the local platform, seed missing definitions, and open its UI.

    Args:
        open_browser: Whether to open the platform in the default browser.
    """
    host_python = None
    if os.environ.get("LANGFUSE_TEST_DEPLOYMENT") != "1":
        from .utils import host_runner_python
        host_python = host_runner_python(PLATFORM_ROOT)
    subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], check=True)
    subprocess.run(["docker", "compose", "version"], check=True)
    environment = prepare_environment()
    compose(["up", "-d", "--wait", "--wait-timeout", "600", "langfuse-web", "langfuse-worker"])
    compose(["build", "experiments"])
    if os.environ.get("LANGFUSE_TEST_DEPLOYMENT") == "1":
        compose(["--profile", "test", "up", "-d", "mock-model"])
        compose(["run", "--rm", "--no-deps", "experiments", "python", "-m", "evals.langfuse.seed"])
    else:
        from .host_runner import start
        from .utils import host_runner_environment
        # The old container and the host must never consume the same job queue.
        compose(["stop", "experiments"])
        subprocess.run([host_python, "-m", "evals.langfuse.seed"],
                       cwd=PLATFORM_ROOT.parent.parent,
                       env=host_runner_environment(PLATFORM_ROOT), check=True)
        start(PLATFORM_ROOT)
    compose(["up", "-d", "--wait", "--wait-timeout", "120", "experiments"])
    print(f"Langfuse: {PUBLIC_URL}\nLogin: evals@chattft.local\nPassword: LANGFUSE_INIT_USER_PASSWORD in {environment}")
    if open_browser:
        webbrowser.open(PUBLIC_URL)


def down() -> None:
    """Stop local services while preserving evaluation content and credentials."""
    if not (PLATFORM_ROOT / ".env").exists():
        print("No local Langfuse environment has been created.")
        return
    from .host_runner import stop
    stop(PLATFORM_ROOT)
    compose(["down"])


def restart_runner() -> None:
    """Reload Python code and settings without restarting the Langfuse platform."""
    if os.environ.get("LANGFUSE_TEST_DEPLOYMENT") == "1":
        compose(["restart", "experiments"])
        return
    from .host_runner import start, stop
    stop(PLATFORM_ROOT)
    start(PLATFORM_ROOT)


def validate() -> None:
    """Validate committed snapshots without starting Docker or calling models."""
    from evals.langfuse.content import load_catalog, load_snapshot, validate_bundle

    from evals.langfuse.utils import validate_case_semantics

    catalog = load_catalog(SNAPSHOT_ROOT)
    count = 0
    for entry in catalog:
        bundle = validate_bundle(load_snapshot(entry["snapshot"], SNAPSHOT_ROOT))
        validate_case_semantics(bundle["suite"], bundle["items"])
        count += len(bundle["items"])
    print(f"Validated {len(catalog)} suites and {count} cases.")


def run(suite: str, *, snapshot: str | None = None, offline: bool = False,
        selection_live: bool = False, data_snapshot_label: str | None = None) -> int:
    """Execute a committed definition for CI or an explicitly requested run.

    Args:
        suite: Stable suite name in the exported catalog.
        snapshot: Optional immutable snapshot identifier overriding the catalog.
        offline: Use local fixture and selector evaluation without Langfuse.
        selection_live: Explicitly enable live model selector execution.
        data_snapshot_label: Label recording evaluation database provenance.

    Returns:
        Zero for a passing run or one for failed assertions.
    """
    from evals.langfuse.content import export_snapshot, load_catalog, load_snapshot, validate_bundle
    from evals.langfuse.experiments import bind_dataset_identity, run_bundle
    from evals.langfuse.utils import catalog_revision, validate_case_semantics

    revision = catalog_revision(SNAPSHOT_ROOT)
    use_live_content = snapshot is None and not offline

    if snapshot is None:
        entry = next((item for item in load_catalog(SNAPSHOT_ROOT) if item["name"] == suite), None)
        if entry is None:
            raise ValueError(f"Unknown suite: {suite}")
        snapshot = entry["snapshot"]
    bundle = load_snapshot(snapshot, SNAPSHOT_ROOT)
    # A UI export may be the latest catalog entry; this command explicitly runs it.
    bundle["config"]["action"] = "run"
    if selection_live:
        bundle["config"]["selection_live"] = True
    if data_snapshot_label is not None:
        bundle["config"]["data_snapshot_label"] = data_snapshot_label
    client = None
    if not offline:
        from langfuse import Langfuse
        from dotenv import dotenv_values
        local = dotenv_values(PLATFORM_ROOT / ".env")
        client = Langfuse(
            base_url=os.environ.get("LANGFUSE_BASE_URL", PUBLIC_URL),
            public_key=os.environ.get("LANGFUSE_PUBLIC_KEY") or local.get("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.environ.get("LANGFUSE_SECRET_KEY") or local.get("LANGFUSE_SECRET_KEY"),
        )
    try:
        if client is not None:
            if use_live_content:
                from .content import fetch_bundle
                from .contracts import DATASET_NAMES
                dataset_name = bundle.get('dataset_name') or DATASET_NAMES[suite]
                bundle = fetch_bundle(client, dataset_name, bundle['config'], SNAPSHOT_ROOT)
            bundle = bind_dataset_identity(bundle, client)
        bundle = validate_bundle(bundle)
        validate_case_semantics(bundle["suite"], bundle["items"])
        snapshot_id = export_snapshot(bundle, SNAPSHOT_ROOT, expected_revision=revision)
        identity = capture_provenance()
        bundle["provenance"] = {
            "git_revision": identity["CHAT_TFT_GIT_REVISION"],
            "working_tree_fingerprint": identity["CHAT_TFT_WORKING_TREE_FINGERPRINT"],
        }
        bundle["snapshot_id"] = snapshot_id
        result = run_bundle(bundle, client=client)
        if result.get('state') == 'awaiting_scores':
            from .jobs import JobStore
            from .grading import reconcile_report
            from .utils import configured_workspace
            import time
            store = JobStore(PLATFORM_ROOT / '.runtime')
            job_id = store.submit(bundle, snapshot_id, awaiting_result=result)
            workspace = configured_workspace()
            try:
                while result['state'] == 'awaiting_scores':
                    try:
                        result = reconcile_report(workspace, result, bundle['grading'])
                        store.awaiting_scores(job_id, result)
                    except Exception:
                        if time.time() >= result['grading_deadline']:
                            result.update(state='failed', passed=False, grading_error='Native grading unavailable at deadline')
                    if result['state'] == 'awaiting_scores':
                        time.sleep(2)
                store.finish(job_id, 'completed' if result['passed'] else 'failed', result=result)
            finally:
                workspace.close()
        result["snapshot"] = snapshot_id
        print(json.dumps(result, indent=2, default=str))
        return 0 if result["passed"] else 1
    finally:
        if client is not None:
            client.flush()
            client.shutdown()


def main(argv: list[str] | None = None) -> int:
    """Dispatch the public evaluation launcher with actionable startup errors.

    Args:
        argv: Optional argument list; defaults to process arguments.

    Returns:
        Process exit code indicating success, failed assertions, or setup error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start = commands.add_parser("up", help="Start and open local Langfuse")
    start.add_argument("--no-browser", action="store_true")
    commands.add_parser("down", help="Stop services and retain their volumes")
    commands.add_parser("restart-runner", help="Reload experiment Python code and configuration")
    commands.add_parser("validate", help="Validate exported evaluation definitions")
    evaluate = commands.add_parser("run", help="Run an exported definition")
    evaluate.add_argument("--suite", default=AssistantName.DUMMY_ASSISTANT)
    evaluate.add_argument("--snapshot")
    evaluate.add_argument("--offline", action="store_true")
    evaluate.add_argument("--selection-live", action="store_true")
    evaluate.add_argument("--data-snapshot-label")
    migrate = commands.add_parser('migrate', help='Export and plan or resume the native workspace migration')
    migrate.add_argument('--directory', type=Path, default=PLATFORM_ROOT / '.runtime')
    migrate.add_argument('--apply', action='store_true')
    export = commands.add_parser('export-workspace', help='Back up complete live definitions and historical links')
    export.add_argument('destination', type=Path)
    review = commands.add_parser('review-baseline', help='Record an explicit baseline review')
    review.add_argument('--snapshot', required=True)
    review.add_argument('--reviewer', required=True)
    review.add_argument('--destination', type=Path, default=PLATFORM_ROOT / '.runtime' / 'reviewed-baseline.json')
    create = commands.add_parser('create-dataset', help='Register and seed a browser-owned assistant dataset')
    create.add_argument('--name', required=True, help='Stable local suite slug')
    create.add_argument('--assistant', default=AssistantName.CHAT, help='Registered assistant to execute')
    create.add_argument('--dataset-name', help='Langfuse name; defaults to chattft/<name>')
    create.add_argument('--description', default='Manual ChatTFT investigations.')
    create.add_argument('--items', type=Path, help='Optional JSON file of initial cases')
    create.add_argument('--database', help='Optional evaluation database default')
    create.add_argument('--max-turns', type=int, default=10)
    create.add_argument('--register-only', action='store_true', help='Write the catalog without starting Langfuse')
    args = parser.parse_args(argv)
    try:
        if args.command == 'migrate':
            from .maintenance import migrate_workspace
            print(json.dumps(migrate_workspace(args.directory, apply=args.apply), indent=2))
        elif args.command == 'export-workspace':
            from .maintenance import export_complete_workspace
            export_complete_workspace(args.destination)
        elif args.command == 'review-baseline':
            from .maintenance import record_reviewed_baseline
            record_reviewed_baseline(args.snapshot, args.reviewer, args.destination)
        elif args.command == "up":
            up(open_browser=not args.no_browser)
        elif args.command == "down":
            down()
        elif args.command == "restart-runner":
            restart_runner()
        elif args.command == "validate":
            validate()
        elif args.command == 'create-dataset':
            from .dataset_registration import register_dataset
            if not args.register_only:
                from .jobs import JobStore
                if JobStore(PLATFORM_ROOT / '.runtime').has_pending():
                    raise ValueError('Finish queued, running, or awaiting-scores experiments before registering a dataset')
            result = register_dataset(
                name=args.name, dataset_name=args.dataset_name or f'chattft/{args.name}',
                assistant=args.assistant, description=args.description,
                items_path=args.items, database=args.database, max_turns=args.max_turns,
                snapshots=SNAPSHOT_ROOT)
            if not args.register_only:
                up(open_browser=False)
                restart_runner()
            print(json.dumps(result, indent=2))
        else:
            return run(args.suite, snapshot=args.snapshot, offline=args.offline,
                       selection_live=args.selection_live, data_snapshot_label=args.data_snapshot_label)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Evaluation launcher: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
