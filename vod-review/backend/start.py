"""Launch the frontend development server and backend together."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    processes: list[subprocess.Popen[bytes]] = []
    exit_code = 0

    try:
        processes.append(subprocess.Popen(["npm", "run", "dev"], cwd=PROJECT_ROOT / "frontend"))
        processes.append(
            subprocess.Popen([sys.executable, "-m", "backend", *sys.argv[1:]], cwd=PROJECT_ROOT)
        )
        while all(process.poll() is None for process in processes):
            time.sleep(0.25)
        exit_code = next(
            process.returncode for process in processes if process.returncode is not None
        )
    except KeyboardInterrupt:
        exit_code = 130
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                process.wait()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
