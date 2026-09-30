"""Process and socket helpers shared by the desktop Python launcher and tests."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, TextIO

if TYPE_CHECKING:
    from uvicorn import Server
    from uvicorn._types import ASGI3Application, ASGIReceiveCallable, ASGISendCallable, Scope


# ---------------------------------------------------------------------------
#
# Backend launcher helpers
# Keep ownership and shutdown independent of the application being imported.
#
# ---------------------------------------------------------------------------


def emit_event(stream: TextIO, event: str, **fields: object) -> None:
    """Write a bounded launcher event without exposing configuration secrets.

    Args:
        stream: Original stdout pipe owned by the Electron parent.
        event: Lifecycle event name understood by the desktop supervisor.
        **fields: Explicit non-secret event metadata.
    """
    stream.write("CHAT_TFT_DESKTOP " + json.dumps({"type": event, **fields}) + "\n")
    stream.flush()


def bind_loopback(port: int) -> socket.socket:
    """Reserve the backend port before advertising it to the desktop parent.

    Args:
        port: TCP port to reserve; zero is permitted for isolated tests.

    Returns:
        Listening socket owned exclusively by this launcher.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Windows otherwise permits another process to reuse some bound sockets.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            # POSIX permits safe listener restart while old connections finish
            # TIME_WAIT. Listening before advertisement still excludes peers.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))
        sock.listen(128)
        return sock
    except BaseException:
        sock.close()
        raise


def watch_parent(
    stream: TextIO,
    shutdown: threading.Event,
    stopped: threading.Event,
    *,
    timeout: float = 10.0,
    force_exit: Callable[[int], object] = os._exit,
) -> None:
    """Request shutdown on a command or orphaned pipe, then bound process exit.

    Args:
        stream: Parent-owned stdin; EOF also means the parent has disappeared.
        shutdown: Event observed by the Uvicorn controller.
        stopped: Event set once the launcher has completed its cleanup.
        timeout: Maximum grace period, including imports or blocked startup.
        force_exit: Last-resort process termination, injectable in unit tests.
    """
    for line in stream:
        if line.strip() == "shutdown":
            break
    shutdown.set()
    # This watchdog also covers a parent crash during synchronous application
    # imports, before the asyncio server has a chance to observe the event.
    if not stopped.wait(timeout):
        force_exit(1)


async def control_shutdown(server: Server, shutdown: threading.Event) -> None:
    """Translate the parent pipe signal into Uvicorn's graceful shutdown request.

    Args:
        server: Uvicorn server owned by this process.
        shutdown: Event set by the parent pipe watcher.
    """
    while not shutdown.is_set():
        await asyncio.sleep(0.1)
    server.should_exit = True


def with_desktop_identity(application: ASGI3Application, identity: str) -> ASGI3Application:
    """Wrap desktop HTTP readiness without altering API, lifespan, or streaming.

    Args:
        application: Existing application imported from the checkout.
        identity: Random per-launch identifier verified across WSL localhost.

    Returns:
        ASGI wrapper serving only the private desktop identity probe itself.
    """
    async def serve_identity(scope: Scope, receive: ASGIReceiveCallable, send: ASGISendCallable) -> None:
        """Answer the desktop ownership probe or delegate the original ASGI call.

        Args:
            scope: ASGI request/lifespan metadata.
            receive: Unmodified inbound event callable.
            send: Unmodified outbound event callable.
        """
        if scope["type"] == "http" and scope["path"] == "/__chattft_desktop__/identity":
            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"x-chattft-desktop-identity", identity.encode("ascii")),
                (b"cache-control", b"no-store"),
            ]})
            await send({"type": "http.response.body", "body": b""})
            return
        await application(scope, receive, send)

    return serve_identity
