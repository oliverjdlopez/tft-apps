"""Unified FastAPI app for the ChatTFT browser experience."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import sys
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles


logger = logging.getLogger(__name__)


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return Path(__file__).resolve().parents[3]


def _ensure_backend_src_on_path() -> None:
    backend_src = _repo_root() / "app" / "backend" / "src"
    if backend_src.exists():
        path = str(backend_src)
        if path not in sys.path:
            sys.path.insert(0, path)


_ensure_backend_src_on_path()

from common.disk_profile import install_disk_profiler, new_request_id, request_scope

install_disk_profiler(_repo_root())

from api.routes import (
    assistants,
    assets,
    compositions,
    chat,
    display,
    flowchart,
    ingest,
    response_tuning,
    rolldown,
    shared_media,
    specs,
)
from core.config import load_config


FRONTEND_DIR = _repo_root() / "app" / "frontend"
STATIC_DIR = FRONTEND_DIR / "dist"
FRONTEND_BUILD_MESSAGE = (
    "ChatTFT frontend assets are not built. Run `cd app/frontend && npm ci && "
    "npm run build` before starting the UI."
)

DATABASE_STATUS_UNKNOWN: dict[str, object] = {
    "available": None,
    "configured": None,
    "warning": None,
}


def _query_table_rebuild_startup_mode() -> str:
    """Return the startup query-table rebuild mode: off, sync, or async."""
    raw = load_config().chat.rebuild_query_tables_on_startup.strip().lower()
    raw = raw.replace("-", "_")
    if raw in {"", "0", "false", "no", "off", "none"}:
        return "off"
    if raw in {"1", "true", "yes", "on", "sync"}:
        return "sync"
    if raw in {"async", "background", "bg"}:
        return "async"
    logger.warning(
        "Ignoring invalid rebuild_query_tables_on_startup=%r; using off",
        load_config().chat.rebuild_query_tables_on_startup,
    )
    return "off"


def _rebuild_query_tables_at_startup() -> None:
    """Catch up ledger-missing matches before agent tools read aggregates."""
    try:
        from db.build_query_tables import catch_up_query_tables
        from db.session import open_db
    except Exception:  # noqa: BLE001 - keep startup diagnostics clear.
        logger.exception("query table rebuild unavailable")
        return

    session = None
    try:
        session = open_db()
        result = catch_up_query_tables(session)
        logger.info("query tables caught up at startup: %s", result)
    except Exception:  # noqa: BLE001 - keep startup failure explicit in logs.
        logger.exception("query table rebuild failed at startup")
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - cleanup must not undo degraded startup.
                logger.exception("database startup session cleanup failed")


async def _rebuild_query_tables_in_background() -> None:
    """Build query tables off the event loop so the UI can serve immediately."""
    await asyncio.to_thread(_rebuild_query_tables_at_startup)


def _start_query_table_rebuild_task() -> Any:
    return asyncio.create_task(
        _rebuild_query_tables_in_background(),
        name="query-table-rebuild",
    )


def _install_local_trace_recorder() -> None:
    """Mirror Agents SDK traces to local JSONL files for dev-time auditing."""
    try:
        from services.tracing_service import ensure_local_trace_processor
    except Exception:  # noqa: BLE001 - tracing should not block the app.
        logger.exception("local trace recorder unavailable")
        return
    ensure_local_trace_processor()


def _warm_database_at_startup() -> dict[str, object]:
    """Warm the database or return a safe degraded-mode status.

    Returns:
        Browser-safe database availability metadata. Database failures are
        intentionally contained so non-database application features can load.
    """
    try:
        from db.session import open_db
    except Exception:  # noqa: BLE001
        logger.exception("database startup warmup unavailable")
        return {
            "available": False,
            "configured": False,
            "warning": "Database features are unavailable because database support could not be loaded.",
        }
    session = None
    try:
        session = open_db()
        session.connection()
        logger.info("database initialized and connection pool warmed")
        return {"available": True, "configured": True, "warning": None}
    except Exception as error:  # noqa: BLE001 - degraded startup is intentional.
        missing_configuration = (
            isinstance(error, ValueError)
            and "incomplete app RDS configuration" in str(error)
        )
        if missing_configuration:
            logger.warning("database startup skipped: %s", error)
            warning = (
                "Database features are unavailable because the RDS connection "
                "values are not configured. Add RDS_HOST, RDS_ADMIN, and RDS_DB "
                "to enable them."
            )
        else:
            logger.exception("database startup warmup failed; continuing without database")
            warning = (
                "Database features are unavailable because the configured RDS "
                "database could not be reached."
            )
        return {
            "available": False,
            "configured": not missing_configuration,
            "warning": warning,
        }
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:  # noqa: BLE001 - cleanup must not undo degraded startup.
                logger.exception("database warmup session cleanup failed")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _install_local_trace_recorder()
    database_status = await asyncio.to_thread(_warm_database_at_startup)
    app.state.database_status = database_status
    rebuild_mode = (
        _query_table_rebuild_startup_mode()
        if database_status["available"]
        else "off"
    )
    query_table_rebuild_task = None
    if rebuild_mode == "sync":
        _rebuild_query_tables_at_startup()
    elif rebuild_mode == "async":
        query_table_rebuild_task = _start_query_table_rebuild_task()
    composition_worker = None
    if load_config().chat.composition_workbench and (
        database_status["available"] or load_config().chat.composition_offline
    ):
        from services.composition_service import CompositionWorker
        composition_worker = CompositionWorker()
        composition_worker.start()
    try:
        yield
    finally:
        if composition_worker is not None:
            await asyncio.to_thread(composition_worker.close)
        if query_table_rebuild_task is not None and not query_table_rebuild_task.done():
            query_table_rebuild_task.cancel()


def create_app() -> FastAPI:
    app = FastAPI(title="chat_tft_api", version="0.3.0", lifespan=_lifespan)
    app.state.database_status = dict(DATABASE_STATUS_UNKNOWN)

    @app.middleware("http")
    async def profile_request_disk_activity(request, call_next):
        """Correlate file activity from a request's full response lifecycle."""
        with request_scope(new_request_id()):
            return await call_next(request)

    app.include_router(assets.router)
    app.mount(
        "/media/tft", assets.EntityMedia(directory=str(assets.service.ASSET_ROOT), check_dir=False),
        name="entity-media",
    )
    app.include_router(compositions.router)
    app.include_router(chat.router)
    app.include_router(display.router)
    app.include_router(flowchart.router)
    app.include_router(response_tuning.router)
    app.include_router(rolldown.router)
    app.include_router(assistants.router)
    app.include_router(ingest.router)
    app.include_router(specs.router)
    app.include_router(shared_media.router)

    @app.get("/")
    def index() -> Response:
        """Serve the Vite build or explain the required local build step."""
        index_path = STATIC_DIR / "index.html"
        if not index_path.exists():
            return PlainTextResponse(FRONTEND_BUILD_MESSAGE, status_code=503)
        return FileResponse(index_path)

    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR), check_dir=False),
        name="static",
    )
    app.mount(
        "/assets",
        StaticFiles(directory=str(STATIC_DIR / "assets"), check_dir=False),
        name="assets",
    )

    @app.exception_handler(404)
    async def not_found(request: Any, exc: Any) -> JSONResponse:  # pragma: no cover
        accepts = request.headers.get("accept", "")
        if "text/html" in accepts and not request.url.path.startswith(("/api/", "/media/")):
            index_path = STATIC_DIR / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            return PlainTextResponse(FRONTEND_BUILD_MESSAGE, status_code=503)
        return JSONResponse({"detail": "Not found"}, status_code=404)

    return app


app = create_app()
