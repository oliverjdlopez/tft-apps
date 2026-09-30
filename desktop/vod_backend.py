"""Run a VOD checkout's backend with the desktop's existing shutdown contract."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import sys
import threading

# Import only launcher helpers before selecting the independent application's path.
sys.path[:] = [entry for entry in sys.path if Path(entry).resolve() != Path(__file__).resolve().parent]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from desktop.utils import bind_loopback, control_shutdown, emit_event, watch_parent, with_desktop_identity


async def serve(repo: Path, port: int, shutdown: threading.Event) -> None:
    """Serve the selected VOD app with an owned socket and no reload subprocess.

    Args:
        repo: Independent VOD checkout with its installed environment.
        port: Fixed workspace backend port.
        shutdown: Parent-pipe cancellation event.
    """
    os.chdir(repo)
    sys.path.insert(0, str(repo))
    with bind_loopback(port) as sock:
        emit_event(sys.stdout, "bound", port=port)
        import uvicorn
        from backend.app import app

        identity = os.environ.get("CHATTFT_DESKTOP_IDENTITY")
        application = with_desktop_identity(app, identity) if identity else app
        server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port,
                                              reload=False, workers=1, timeout_graceful_shutdown=5))
        controller = asyncio.create_task(control_shutdown(server, shutdown))
        try:
            if not shutdown.is_set():
                await server.serve(sockets=[sock])
        finally:
            controller.cancel()
            await asyncio.gather(controller, return_exceptions=True)


def main() -> None:
    """Start a fresh interpreter that exits when its owning desktop disconnects."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    shutdown = threading.Event()
    stopped = threading.Event()
    threading.Thread(target=watch_parent, args=(sys.stdin, shutdown, stopped), daemon=True).start()
    try:
        asyncio.run(serve(args.repo.resolve(), args.port, shutdown))
    finally:
        stopped.set()


if __name__ == "__main__":
    main()
