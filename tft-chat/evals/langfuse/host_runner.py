"""Retire the former host runner without interrupting accepted evaluations."""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import signal
import time

from .utils import host_runner_pid, require_idle_runner


def stop(root: Path) -> None:
    """Retire an idle, verified host process and preserve all evaluation history.

    Args:
        root: Host path of the suite-owned Langfuse directory.

    Raises:
        ValueError: Accepted work remains pending or the owned process will not stop.
    """
    runtime = root / '.runtime'
    if not runtime.exists():
        return
    with (runtime / 'runner.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        require_idle_runner(runtime)
        pid = host_runner_pid(root)
        if pid is not None:
            os.killpg(pid, signal.SIGTERM)
            for _ in range(100):
                if host_runner_pid(root) is None:
                    break
                time.sleep(.1)
            else:
                # Do not destroy a slow shutdown or start a competing consumer.
                raise ValueError('Legacy host runner did not stop; inspect it before starting the container')
        (runtime / 'runner.pid').unlink(missing_ok=True)
        (runtime / 'runner.sock').unlink(missing_ok=True)
