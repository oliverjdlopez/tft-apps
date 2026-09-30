"""Exercise the VOD launcher with a temporary checkout and no video dependencies."""

from pathlib import Path
import os
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from desktop.utils import bind_loopback


@pytest.mark.parametrize("disconnect", [False, True])
def test_vod_backend_uses_checkout_and_honors_parent(tmp_path: Path, disconnect: bool) -> None:
    """Load a separate checkout and exit on explicit shutdown or parent EOF.

    Args:
        tmp_path: Isolated checkout directory provided by pytest.
        disconnect: Whether to close the parent pipe instead of sending shutdown.
    """
    package = tmp_path / "backend"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "app.py").write_text(
        'from fastapi import FastAPI\n'
        'from pathlib import Path\n'
        'app = FastAPI()\n'
        '@app.get("/api/health")\n'
        'async def health():\n'
        '    return {"checkout": Path.cwd().name}\n'
    )
    with bind_loopback(0) as reservation:
        port = reservation.getsockname()[1]
    launcher = Path(__file__).resolve().parents[1] / "vod_backend.py"
    child = subprocess.Popen(
        [sys.executable, str(launcher), "--repo", str(tmp_path), "--port", str(port)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        env={**os.environ, "CHATTFT_DESKTOP_IDENTITY": "vod-fixture"},
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.3) as response:
                    assert tmp_path.name.encode() in response.read()
                break
            except URLError:
                if child.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail("VOD fixture failed to start")
                time.sleep(0.05)
        with urlopen(f"http://127.0.0.1:{port}/__chattft_desktop__/identity") as response:
            assert response.headers["x-chattft-desktop-identity"] == "vod-fixture"
        if not disconnect:
            child.stdin.write(b"shutdown\n")
            child.stdin.flush()
        else:
            child.stdin.close()
        assert child.wait(timeout=15) == 0
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stderr.close()
