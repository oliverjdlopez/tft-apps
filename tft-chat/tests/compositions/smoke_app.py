"""Isolated HTTP application for the real Electron composition UI smoke test."""

from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from api.routes.compositions import router, require_workbench
from db.session import open_db
from services.compositions import persistence, source
from services.compositions.worker import CompositionWorker

# This explicit test entrypoint can only use the guarded RDS_TEST_* target.
persistence.open_db = lambda: open_db(purpose="test")
source.open_db = lambda: open_db(purpose="test")


@asynccontextmanager
async def lifespan(app):
    """Own a worker against the isolated database for the duration of the smoke app."""
    open_db(purpose="test").close()
    worker = CompositionWorker(purpose="test")
    worker.start()
    try:
        yield
    finally:
        worker.close()


app = FastAPI(lifespan=lifespan)
app.dependency_overrides[require_workbench] = lambda: None
app.include_router(router)
frontend = Path(__file__).resolve().parents[2] / "app/frontend/dist"
app.mount("/assets", StaticFiles(directory=frontend / "assets"), name="assets")


@app.get("/api/config")
def config():
    """Enable only the composition UI in the isolated smoke application."""
    return {"composition_workbench": True}


@app.get("/compositions")
def index():
    """Serve the actual production React build for native renderer validation."""
    return FileResponse(frontend / "index.html")
