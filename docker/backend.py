"""Serve one suite application with container signals and desktop identity."""

from __future__ import annotations

import argparse
from importlib import import_module
import os
from pathlib import Path
import sys
from typing import Any


def mount_vod_frontend(application: Any, directory: Path) -> None:
    """Append safe frontend serving after the VOD application's API routes.

    Args:
        application: Existing FastAPI application with its own lifespan.
        directory: Image-built Vite output, never a media or data directory.
    """
    from fastapi import HTTPException, Request
    from fastapi.responses import FileResponse, PlainTextResponse

    root = directory.resolve()

    async def frontend(request: Request) -> Any:
        """Serve an existing public asset or an HTML-only client route.

        Args:
            request: Request not matched by an earlier application route.

        Returns:
            A static file or the SPA shell; unavailable builds return 503.
        """
        relative = request.path_params.get("path", "")
        if relative == "api" or relative.startswith(("api/", "__chattft_desktop__/")):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=404, detail="Not found")
        if candidate.is_file():
            return FileResponse(candidate)
        # Missing scripts and other assets must remain failures. Returning HTML
        # here would mask missing builds and confuse browser module loading.
        if relative and (candidate.suffix or "text/html" not in request.headers.get("accept", "")):
            raise HTTPException(status_code=404, detail="Not found")
        index = root / "index.html"
        if not index.is_file():
            return PlainTextResponse("Frontend build unavailable; rebuild the VOD image.", status_code=503)
        return FileResponse(index)

    # Setting the concrete annotation avoids resolving the nested Request type
    # against module globals when FastAPI inspects postponed annotations.
    frontend.__annotations__["request"] = Request
    application.add_api_route("/{path:path}", frontend, methods=["GET", "HEAD"], include_in_schema=False)


def load_application(service: str, suite_root: Path | None = None) -> Any:
    """Import the selected app from its own source root and retain its lifespan.

    Args:
        service: Either chat or vod; each uses a separate dependency image.
        suite_root: Image root, optionally overridden for isolated tests.

    Returns:
        The app, wrapped with the desktop's per-launch identity when supplied.
    """
    if service not in {"chat", "vod"}:
        raise ValueError("Unknown application service")
    suite = (suite_root or Path(__file__).resolve().parent.parent).resolve()
    app_root = suite / ("tft-chat" if service == "chat" else "vod-review")
    # The script itself is named backend.py. Remove its directory so imports of
    # VOD's backend package cannot accidentally resolve this entrypoint instead.
    script_directory = Path(__file__).resolve().parent
    sys.path[:] = [entry for entry in sys.path if Path(entry).resolve() != script_directory]
    sys.path[:0] = [str(app_root), str(suite)]
    if service == "chat":
        sys.path[:0] = [str(app_root / "app/backend"), str(app_root / "app/backend/src")]
    os.chdir(app_root)
    application = import_module("api.app" if service == "chat" else "backend.app").app
    if service == "vod":
        mount_vod_frontend(application, app_root / "frontend/dist")
    identity = os.environ.get("CHATTFT_DESKTOP_IDENTITY")
    if identity:
        from desktop.utils import with_desktop_identity

        return with_desktop_identity(application, identity)
    return application


def main() -> None:
    """Run a single Uvicorn process with normal SIGTERM/SIGINT handling."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service", choices=["chat", "vod"], required=True)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    port = args.port if args.port is not None else (8300 if args.service == "chat" else 8000)
    if not 1 <= port <= 65535:
        parser.error("port must be between 1 and 65535")
    import uvicorn

    uvicorn.run(
        load_application(args.service), host="0.0.0.0", port=port,
        workers=1, reload=False, timeout_graceful_shutdown=20,
    )


if __name__ == "__main__":
    main()
