"""Manage the host Python experiment service independently of Docker's lifetime."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import subprocess
import time

from .utils import host_runner_environment, host_runner_pid, host_runner_ready, host_runner_python


def start(root: Path) -> None:
    """Start one detached host runner, or reuse a healthy process for this checkout.

    Args:
        root: Absolute Langfuse directory containing private runtime state.
    """
    runtime = root / '.runtime'
    runtime.mkdir(parents=True, exist_ok=True)
    with (runtime / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pid = host_runner_pid(root)
        if pid is not None:
            if host_runner_ready(root):
                return
            raise ValueError('Host runner is unhealthy; stop it with chat-tft-evals down before restarting')
        socket = runtime / 'runner.sock'
        socket.unlink(missing_ok=True)
        # Restrict both log and socket access to the invoking user and group.
        descriptor = os.open(runtime / 'runner.log', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(descriptor, 'ab') as log:
            process = subprocess.Popen([host_runner_python(root), '-m', 'uvicorn', 'evals.langfuse.server:app',
                '--uds', str(socket)], cwd=root.parent.parent, env=host_runner_environment(root),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, umask=0o007)
        (runtime / 'runner.pid').write_text(str(process.pid))
        for _ in range(100):
            if process.poll() is not None:
                raise ValueError(f'Host runner exited; inspect {runtime / "runner.log"}')
            if host_runner_ready(root):
                socket.chmod(0o660)
                return
            time.sleep(.1)
        os.killpg(process.pid, signal.SIGTERM)
        raise ValueError(f'Host runner did not become ready; inspect {runtime / "runner.log"}')


def stop(root: Path) -> None:
    """Stop only the verified owned process group and preserve all evaluation history."""
    runtime = root / '.runtime'
    if not runtime.exists():
        return
    with (runtime / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pid = host_runner_pid(root)
        if pid is not None:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(100):
                if host_runner_pid(root) is None:
                    break
                time.sleep(.1)
            else:
                os.killpg(pid, signal.SIGKILL)
        (runtime / 'runner.pid').unlink(missing_ok=True)
        (runtime / 'runner.sock').unlink(missing_ok=True)
