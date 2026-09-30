"""Run the existing FastAPI app with a desktop-owned socket and shutdown pipe."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
import threading
import os


REPO_ROOT = Path(__file__).resolve().parent.parent
# Python adds the script directory to sys.path. Its utils.py would otherwise
# override the backend's namespace package utils, even with src inserted first.
sys.path[:] = [entry for entry in sys.path if Path(entry).resolve() != REPO_ROOT / "desktop"]
# Direct script execution must resolve the same repository modules as the
# installed CLI, even when npm was invoked from a different working directory.
sys.path[:0] = [str(REPO_ROOT), str(REPO_ROOT / "app/backend"), str(REPO_ROOT / "app/backend/src")]

from desktop.utils import bind_loopback, control_shutdown, emit_event, watch_parent, with_desktop_identity


async def serve(port: int | None, shutdown: threading.Event) -> None:
    """Serve the normal application while honoring the desktop parent's lifetime.

    Args:
        port: One-run port override; otherwise use the canonical UI setting.
        shutdown: Cross-platform parent shutdown signal.
    """
    import uvicorn
    from core.config import load_config

    config = load_config()
    selected_port = config.chat.ui_port if port is None else port
    if not 1 <= selected_port <= 65535:
        emit_event(sys.stdout, "error", message="Backend port must be between 1 and 65535.")
        raise SystemExit(1)
    try:
        sock = bind_loopback(selected_port)
    except OSError:
        emit_event(
            sys.stdout,
            "error",
            message=f"Cannot bind backend port {selected_port}. Stop the other server or use --port.",
        )
        raise SystemExit(1) from None

    with sock:
        emit_event(sys.stdout, "bound", port=selected_port)
        application = "api.app:app"
        identity = os.environ.get("CHATTFT_DESKTOP_IDENTITY")
        if identity:
            from api.app import app
            application = with_desktop_identity(app, identity)
        server = uvicorn.Server(uvicorn.Config(
            application, host="127.0.0.1", port=selected_port,
            reload=False, workers=1, timeout_graceful_shutdown=5,
        ))
        controller = asyncio.create_task(control_shutdown(server, shutdown))
        try:
            if not shutdown.is_set():
                await server.serve(sockets=[sock])
        finally:
            controller.cancel()
            await asyncio.gather(controller, return_exceptions=True)


def main() -> None:
    """Launch from the native checkout environment without creating worker trees."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    shutdown = threading.Event()
    stopped = threading.Event()
    threading.Thread(
        target=watch_parent, args=(sys.stdin, shutdown, stopped), daemon=True,
    ).start()
    try:
        asyncio.run(serve(args.port, shutdown))
    except Exception:
        # Existing backend diagnostics remain in the launching terminal. The UI
        # only receives fixed messages, never arbitrary exception/config values.
        emit_event(sys.stdout, "error", message="Backend startup failed. Check Python dependencies and configuration in the launch terminal.")
        raise
    finally:
        stopped.set()


if __name__ == "__main__":
    main()
