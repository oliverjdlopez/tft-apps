"""Exercise persistent local credential and lifecycle protections."""

from pathlib import Path
from unittest.mock import patch

from evals.langfuse import launcher


def test_environment_is_private_and_stable(tmp_path: Path) -> None:
    """Repeated startup preserves credentials already paired with stored data."""
    path = launcher.prepare_environment(tmp_path)
    original = path.read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert b"GENERATED" not in original
    assert len(dict(line.split("=", 1) for line in original.decode().splitlines())["ENCRYPTION_KEY"]) == 64
    assert launcher.prepare_environment(tmp_path).read_bytes() == original
    assert (tmp_path / ".runtime").is_dir()


def test_down_preserves_volumes(tmp_path: Path, monkeypatch) -> None:
    """The stop command never deletes persisted platform state."""
    launcher.prepare_environment(tmp_path)
    monkeypatch.setattr(launcher, "PLATFORM_ROOT", tmp_path)
    with patch.object(launcher, "compose") as compose:
        launcher.down()
    compose.assert_called_once_with(["down"])


def test_start_seeds_before_worker_and_does_not_print_secrets(tmp_path: Path, capsys, monkeypatch) -> None:
    """Startup seeds missing content before accepting UI experiment requests."""
    monkeypatch.setenv("LANGFUSE_TEST_DEPLOYMENT", "1")
    (tmp_path / ".env").write_text("LANGFUSE_INIT_USER_EMAIL=custom@example.test\nLANGFUSE_INIT_USER_PASSWORD=private-test-value\n")
    with patch.object(launcher.subprocess, "run"), patch.object(launcher, "prepare_environment", return_value=tmp_path / ".env"), patch.object(launcher, "compose") as compose:
        launcher.up(open_browser=False)
    calls = [call.args[0] for call in compose.call_args_list]
    assert calls[3] == ["run", "--rm", "--no-deps", "experiments", "python", "-m", "evals.langfuse.seed"]
    assert calls[4][-1] == "experiments"
    output = capsys.readouterr().out
    assert "Login: custom@example.test" in output
    assert "LANGFUSE_INIT_USER_PASSWORD" in output
    assert "private-test-value" not in output


def test_provenance_detects_untracked_content(tmp_path: Path) -> None:
    """Editing a new source file changes provenance before its first commit."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-qm", "initial"], cwd=tmp_path, check=True)
    source = tmp_path / "new.py"
    source.write_text("value = 1\n")
    before = launcher.capture_provenance(tmp_path)
    source.write_text("value = 2\n")
    after = launcher.capture_provenance(tmp_path)
    assert before["CHAT_TFT_GIT_REVISION"] == after["CHAT_TFT_GIT_REVISION"]
    assert before["CHAT_TFT_WORKING_TREE_FINGERPRINT"] != after["CHAT_TFT_WORKING_TREE_FINGERPRINT"]


def test_run_exports_effective_definition_before_execution(tmp_path: Path, monkeypatch) -> None:
    """CLI flags enter the immutable bundle before an evaluator can run."""
    from copy import deepcopy
    from evals.langfuse import content, experiments

    bundle = content.load_snapshot(
        "548ed5b704124f3d59fc4a097b4c8246ee54f1a76a889009e9ebb138764fb099",
        launcher.SNAPSHOT_ROOT,
    )
    bundle["config"]["action"] = "export"
    original = content.export_snapshot(bundle, tmp_path)
    monkeypatch.setattr(launcher, "SNAPSHOT_ROOT", tmp_path)
    monkeypatch.setenv("LANGFUSE_RUNTIME_DIR", str(tmp_path / "runtime"))
    received = []

    def evaluate(value, client=None):
        """Inspect the already exported definition at execution admission."""
        received.append(deepcopy(value))
        frozen = content.load_snapshot(value["snapshot_id"], tmp_path)
        assert frozen["config"]["data_snapshot_label"] == "test-data"
        assert frozen["config"]["action"] == "run"
        assert "provenance" not in frozen
        return {"passed": True}

    monkeypatch.setattr(experiments, "run_bundle", evaluate)
    assert launcher.run("dummy_assistant", offline=True, data_snapshot_label="test-data") == 0
    assert received[0]["snapshot_id"] != original
    assert received[0]["provenance"]["git_revision"]
    assert launcher.run("dummy_assistant", offline=True, data_snapshot_label="test-data") == 0
    assert received[0]["snapshot_id"] == received[1]["snapshot_id"]


def test_host_start_stops_container_consumer_before_starting_host(tmp_path, monkeypatch):
    """Default startup cannot leave two consumers competing for the durable queue."""
    from evals.langfuse import host_runner, utils
    monkeypatch.delenv('LANGFUSE_TEST_DEPLOYMENT', raising=False)
    monkeypatch.setattr(launcher, 'PLATFORM_ROOT', tmp_path)
    monkeypatch.setattr(utils, 'host_runner_python', lambda root: '/python')
    events = []
    with patch.object(launcher, 'prepare_environment', return_value=tmp_path / '.env'), \
         patch.object(launcher, 'compose', side_effect=lambda args: events.append(args)), \
         patch.object(launcher.subprocess, 'run', side_effect=lambda args, **kw: events.append(args)), \
         patch.object(host_runner, 'start', side_effect=lambda root: events.append(['host-start'])):
        launcher.up(open_browser=False)
    assert events.index(['stop', 'experiments']) < events.index(['host-start'])
    assert ['/python', '-m', 'evals.langfuse.seed'] in events
    assert events[-1][-1] == 'experiments'


def test_host_environment_preserves_local_database_and_credentials(tmp_path, monkeypatch):
    """Host execution retains localhost database coordinates without logging secrets."""
    from evals.langfuse.utils import host_runner_environment
    root = tmp_path / 'evals/langfuse'
    root.mkdir(parents=True)
    (tmp_path / '.env').write_text('RDS_HOST=127.0.0.1\nRDS_PASSWORD=private\n')
    (root / '.env').write_text('LANGFUSE_SECRET_KEY=platform-secret\n')
    monkeypatch.delenv('RDS_HOST', raising=False)
    monkeypatch.delenv('RDS_PASSWORD', raising=False)
    environment = host_runner_environment(root)
    assert environment['RDS_HOST'] == '127.0.0.1'
    assert environment['RDS_PASSWORD'] == 'private'
    assert environment['LANGFUSE_BASE_URL'] == 'http://localhost:15510'
    assert environment['LANGFUSE_SECRET_KEY'] == 'platform-secret'


def test_stop_does_not_signal_unrelated_pid(tmp_path):
    """A stale PID file cannot terminate an unrelated host process."""
    import os
    from evals.langfuse.host_runner import stop
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'runner.pid').write_text(str(os.getpid()))
    with patch('os.killpg') as signal:
        stop(tmp_path)
    signal.assert_not_called()
