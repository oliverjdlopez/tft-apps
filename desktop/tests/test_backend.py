"""Check native Python process ownership with stdlib tests and a minimal ASGI app."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import unittest
from urllib.request import urlopen

from desktop.utils import bind_loopback, emit_event, watch_parent


class OwnershipTests(unittest.TestCase):
    """Test socket exclusivity and orphan detection without application dependencies."""

    def test_script_directory_does_not_shadow_backend_namespace_packages(self) -> None:
        """Direct desktop launch must resolve backend utils.tft rather than utils.py."""
        desktop = Path(__file__).resolve().parents[1]
        script = (
            "import sys, runpy, importlib.util; "
            f"sys.path.insert(0, {str(desktop)!r}); "
            f"runpy.run_path({str(desktop / 'backend.py')!r}); "
            "assert importlib.util.find_spec('utils.tft').origin.endswith('utils/tft.py')"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_socket_is_exclusive(self) -> None:
        """A second launcher cannot take ownership of an existing backend port."""
        with bind_loopback(0) as first:
            with self.assertRaises(OSError):
                bind_loopback(first.getsockname()[1])

    def test_shutdown_and_eof_request_graceful_exit(self) -> None:
        """Both a normal quit and an orphaned pipe trigger the same cleanup path."""
        for data in ("shutdown\n", ""):
            shutdown, stopped = threading.Event(), threading.Event()
            stopped.set()
            watch_parent(io.StringIO(data), shutdown, stopped, force_exit=self.fail)
            self.assertTrue(shutdown.is_set())

    def test_stalled_shutdown_uses_bounded_fallback(self) -> None:
        """An unresponsive server cannot survive indefinitely after parent loss."""
        codes = []
        watch_parent(io.StringIO(""), threading.Event(), threading.Event(), timeout=0, force_exit=codes.append)
        self.assertEqual(codes, [1])

    def test_protocol_only_contains_explicit_metadata(self) -> None:
        """Lifecycle output is parseable without serializing application settings."""
        output = io.StringIO()
        emit_event(output, "bound", port=8300)
        self.assertEqual(json.loads(output.getvalue().removeprefix("CHAT_TFT_DESKTOP ")), {"type": "bound", "port": 8300})


@unittest.skipUnless(importlib.util.find_spec("uvicorn"), "Install Python dependencies to exercise Uvicorn")
class BackendProcessTests(unittest.TestCase):
    """Run the actual desktop server lifecycle without model calls or database writes."""

    def start_backend(self, *, port: int | None = None, stall: bool = False, identity: str | None = None) -> tuple[subprocess.Popen, int, queue.Queue]:
        """Spawn the isolated ASGI fixture and collect stdout without blocking tests.

        Args:
            port: Explicit port, optionally already occupied by another socket.
            stall: Whether to simulate an application stuck in lifespan startup.
            identity: Optional WSL ownership identifier for the desktop-only probe.

        Returns:
            Child process, selected port, and queue of lifecycle output lines.
        """
        if port is None:
            with bind_loopback(0) as reservation:
                port = reservation.getsockname()[1]
        command = [sys.executable, "-u", str(Path(__file__).parent / "fixtures/backend.py"), str(port)]
        if stall:
            command.append("--stall")
        env = dict(os.environ)
        if identity:
            env["CHATTFT_DESKTOP_IDENTITY"] = identity
        child = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        self.addCleanup(self.stop_backend, child)
        lines = queue.Queue()
        threading.Thread(target=self.collect_lines, args=(child, lines), daemon=True).start()
        return child, port, lines

    @staticmethod
    def collect_lines(child: subprocess.Popen, lines: queue.Queue) -> None:
        """Collect stdout on a thread so a broken child cannot hang the test reader.

        Args:
            child: Running fixture process.
            lines: Queue receiving output lines.
        """
        for line in child.stdout:
            lines.put(line)

    @staticmethod
    def stop_backend(child: subprocess.Popen) -> None:
        """Reap fixture processes even when an assertion fails.

        Args:
            child: Fixture process owned by the test.
        """
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()

    def wait_ready(self, port: int) -> None:
        """Wait for fixture HTTP startup with a fixed deadline.

        Args:
            port: Fixture's exclusively owned backend port.
        """
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/api/config", timeout=0.2) as response:
                    self.assertEqual(response.status, 200)
                    return
            except OSError:
                time.sleep(0.05)
        self.fail("Backend did not become ready")

    def test_normal_shutdown_and_parent_disconnect(self) -> None:
        """The real Uvicorn process exits and releases its port on command or EOF."""
        for command in ("shutdown\n", ""):
            child, port, lines = self.start_backend()
            self.assertIn('"type": "bound"', lines.get(timeout=8))
            self.wait_ready(port)
            child.stdin.write(command)
            child.stdin.flush()
            child.stdin.close()
            self.assertEqual(child.wait(timeout=15), 0)
            # A connection failure confirms there is no remaining listening server;
            # rebinding can temporarily be restricted by TCP TIME_WAIT on Windows.
            with socket.socket() as probe:
                self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)

    def test_occupied_port_fails_before_readiness(self) -> None:
        """The Python launcher reports a bind failure instead of adopting a server."""
        with bind_loopback(0) as existing:
            child, _, lines = self.start_backend(port=existing.getsockname()[1])
            self.assertIn("Cannot bind backend port", lines.get(timeout=8))
            self.assertNotEqual(child.wait(timeout=5), 0)

    def test_wsl_identity_probe_preserves_application_and_shutdown(self) -> None:
        """Desktop identity is served by its wrapper while API and lifespan delegate."""
        child, port, lines = self.start_backend(identity="owned-wsl-backend")
        self.assertIn('"type": "bound"', lines.get(timeout=8))
        self.wait_ready(port)
        with urlopen(f"http://127.0.0.1:{port}/__chattft_desktop__/identity") as response:
            self.assertEqual(response.headers["x-chattft-desktop-identity"], "owned-wsl-backend")
            self.assertEqual(response.headers["cache-control"], "no-store")
        with urlopen(f"http://127.0.0.1:{port}/api/config") as response:
            self.assertEqual(response.read(), b"{}")
        child.stdin.close()
        self.assertEqual(child.wait(timeout=15), 0)

    @unittest.skipIf(sys.platform == "win32", "Windows exclusive sockets may wait for connection teardown")
    def test_backend_can_restart_on_same_port(self) -> None:
        """A normal restart on POSIX must not get stuck behind TCP TIME_WAIT."""
        port = None
        for _ in range(2):
            child, port, lines = self.start_backend(port=port)
            self.assertIn('"type": "bound"', lines.get(timeout=8))
            self.wait_ready(port)
            child.stdin.close()
            self.assertEqual(child.wait(timeout=15), 0)

    def test_parent_loss_during_stalled_startup_is_bounded(self) -> None:
        """The watchdog stops startup even when ASGI never yields control back."""
        child, _, lines = self.start_backend(stall=True)
        self.assertIn('"type": "bound"', lines.get(timeout=8))
        time.sleep(0.3)
        child.stdin.close()
        self.assertNotEqual(child.wait(timeout=15), 0)


if __name__ == "__main__":
    unittest.main()
