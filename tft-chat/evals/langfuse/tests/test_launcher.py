"""Exercise persistent local credential and lifecycle protections."""

from pathlib import Path
from unittest.mock import patch

import pytest

from evals.langfuse import launcher
from domain.assistants.constants import AssistantName


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
    monkeypatch.setenv("LANGFUSE_TEST_DEPLOYMENT", "1")
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
    assert launcher.run(AssistantName.DUMMY_ASSISTANT, offline=True, data_snapshot_label="test-data") == 0
    assert received[0]["snapshot_id"] != original
    assert received[0]["provenance"]["git_revision"]
    assert launcher.run(AssistantName.DUMMY_ASSISTANT, offline=True, data_snapshot_label="test-data") == 0
    assert received[0]["snapshot_id"] == received[1]["snapshot_id"]


@pytest.mark.parametrize(('operation', 'action'), [
    ('up', 'langfuse-up'), ('down', 'eval-down'), ('restart_runner', 'eval-restart'),
])
def test_normal_lifecycle_delegates_to_desktop(tmp_path, monkeypatch, operation, action):
    """All normal lifecycle changes use the common container and retirement gate."""
    monkeypatch.delenv('LANGFUSE_TEST_DEPLOYMENT', raising=False)
    root = tmp_path / 'tft-chat/evals/langfuse'
    launcher.prepare_environment(root)
    monkeypatch.setattr(launcher, 'PLATFORM_ROOT', root)
    with patch.object(launcher.subprocess, 'run') as execute, \
         patch.object(launcher, 'compose') as compose:
        getattr(launcher, operation)(**({'open_browser': False} if operation == 'up' else {}))
    execute.assert_called_once_with(['node', str(tmp_path / 'desktop/docker.mjs'), action], check=True)
    compose.assert_not_called()


def test_normal_compose_delegates_arguments_to_desktop(tmp_path, monkeypatch):
    """Developer commands receive the same credentials and mounts as desktop startup."""
    monkeypatch.delenv('LANGFUSE_TEST_DEPLOYMENT', raising=False)
    root = tmp_path / 'tft-chat/evals/langfuse'
    with patch.object(launcher.subprocess, 'run') as execute:
        launcher.compose(['logs', '--tail', '100', 'experiments'], root)
    execute.assert_called_once_with([
        'node', str(tmp_path / 'desktop/docker.mjs'), 'eval-compose',
        'logs', '--tail', '100', 'experiments'], check=True)


def test_test_compose_keeps_isolated_configuration(tmp_path, monkeypatch):
    """CI bypasses desktop configuration and explicitly applies its mock overlay."""
    monkeypatch.setenv('LANGFUSE_TEST_DEPLOYMENT', '1')
    with patch.object(launcher, 'capture_provenance', return_value={}), \
         patch.object(launcher.subprocess, 'run') as execute:
        launcher.compose(['config', '--quiet'], tmp_path)
    command = execute.call_args.args[0]
    assert command[:2] == ['docker', 'compose']
    assert str(tmp_path / 'compose.test.yaml') in command
    assert execute.call_args.kwargs['env']['LANGFUSE_LLM_CONNECTION_WHITELISTED_HOST'] == 'mock-model'


def test_queue_status_does_not_create_runtime(tmp_path, monkeypatch, capsys):
    """The migration preflight is read-only even before the first accepted job."""
    import json
    runtime = tmp_path / 'absent'
    monkeypatch.setenv('LANGFUSE_RUNTIME_DIR', str(runtime))
    assert launcher.main(['runner-status']) == 0
    assert json.loads(capsys.readouterr().out) == {'pending': False, 'jobs': []}
    assert not runtime.exists()


@pytest.mark.parametrize('state', ['queued', 'running', 'awaiting_scores'])
def test_queue_status_blocks_every_pending_state(tmp_path, state):
    """Migration cannot cancel execution or discard asynchronous grading work."""
    from evals.langfuse.jobs import JobStore
    from evals.langfuse.host_runner import stop
    from evals.langfuse.utils import runner_queue_status
    runtime = tmp_path / '.runtime'
    store = JobStore(runtime)
    identity = store.submit({'private': 'not exposed'}, 'test-snapshot')
    with store.connect() as connection:
        connection.execute('UPDATE jobs SET state=? WHERE id=?', (state, identity))
    before = store.path.read_bytes()
    assert runner_queue_status(runtime) == {'pending': True, 'jobs': [{'id': identity, 'state': state}]}
    assert store.path.read_bytes() == before
    with patch('os.killpg') as signal, pytest.raises(ValueError, match='Finish queued'):
        stop(tmp_path)
    signal.assert_not_called()
    assert store.get(identity)['state'] == state


def test_queue_status_keeps_terminal_history(tmp_path):
    """An idle queue can migrate without modifying its historical results."""
    from evals.langfuse.jobs import JobStore
    from evals.langfuse.utils import runner_queue_status
    store = JobStore(tmp_path)
    identity = store.submit({}, 'test-snapshot')
    store.finish(identity, 'failed', error='retained historical error')
    before = store.path.read_bytes()
    assert runner_queue_status(tmp_path) == {'pending': False, 'jobs': []}
    assert store.path.read_bytes() == before
    assert store.get(identity)['error'] == 'retained historical error'


def test_unreadable_queue_fails_closed(tmp_path, monkeypatch, capsys):
    """A broken existing database is never treated as permission to retire a runner."""
    (tmp_path / 'jobs.sqlite3').write_bytes(b'not sqlite')
    monkeypatch.setenv('LANGFUSE_RUNTIME_DIR', str(tmp_path))
    assert launcher.main(['runner-status']) == 2
    output = capsys.readouterr()
    assert not output.out
    assert 'Cannot verify' in output.err


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
