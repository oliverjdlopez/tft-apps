"""Own an ephemeral PostgreSQL 16 container for the required integration tier."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import signal
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def main():
    """Create an isolated target, run the tier, and remove only the owned container."""
    name = "tft-validation-" + uuid4().hex[:12]
    def interrupted(signum, frame):
        """Unwind the owned container cleanup if an operator cancels validation."""
        raise KeyboardInterrupt(f"Database validation interrupted by signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    command = ["docker", "run", "--rm", "--detach", "--name", name,
               "--publish", "127.0.0.1::5432", "--env", "POSTGRES_USER=tft",
               "--env", "POSTGRES_PASSWORD=validation-only", "--env", "POSTGRES_DB=validation_test", "postgres:16"]
    created = False
    container_log = ROOT / "dev" / "logs" / "validation" / "postgres" / f"{name}.log"
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=120)
        created = True
        port = subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True, timeout=10).strip().rsplit(":", 1)[1]
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            probe = subprocess.run(["docker", "exec", name, "pg_isready", "-U", "tft", "-d", "validation_test"], capture_output=True, timeout=10)
            if probe.returncode == 0:
                break
            time.sleep(0.2)
        else:
            raise TimeoutError("Isolated PostgreSQL 16 failed to become ready")
        env = {**os.environ, "RDS_TEST_HOST": "127.0.0.1", "RDS_TEST_PORT": port,
               "RDS_TEST_ADMIN": "tft", "RDS_TEST_PASSWORD": "validation-only",
               "RDS_TEST_DB": "validation_test", "RDS_TEST_SYNC_LOCAL_IP": "0",
               "VALIDATION_CONTAINER_LOG": str(container_log)}
        return subprocess.call([sys.executable, str(ROOT / "scripts/test_suite.py"), "--tier", "postgres", "--component", "chat", *sys.argv[1:]], env=env, cwd=ROOT)
    finally:
        if created:
            container_log.parent.mkdir(parents=True, exist_ok=True)
            with container_log.open("w") as stream:
                subprocess.run(["docker", "logs", name], stdout=stream, stderr=subprocess.STDOUT, timeout=10)
            subprocess.run(["docker", "stop", "--time", "5", name], check=True, capture_output=True, timeout=15)


if __name__ == "__main__":
    raise SystemExit(main())
