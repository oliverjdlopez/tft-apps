"""Serve the production Flowchart with disposable stores, without production startup.

Run with ``uv run python -m uvicorn --app-dir tests flowchart_smoke_server:app``.
All workspace rows, library fragments, and exports live in a temporary directory.
"""
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app/backend"), str(ROOT / "app/backend/src")]

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api.routes import flowchart
from db.models import DevFlowchartGroup, DevWorkspace
from services.flowchart import service

store = TemporaryDirectory(prefix="flowchart-smoke-")
engine = create_engine(f"sqlite:///{store.name}/workspaces.sqlite", connect_args={"check_same_thread": False})
DevWorkspace.__table__.create(engine)
DevFlowchartGroup.__table__.create(engine)
sessions = sessionmaker(engine, expire_on_commit=False)
# This process never runs the production lifespan or opens an RDS connection.
# Patch only the private workspace service, leaving other domain APIs unmounted.
service.open_db = lambda: sessions()
service.GAMEPLANS_DIR = Path(store.name) / "gameplans"
flowchart.load_config = lambda: SimpleNamespace(chat=SimpleNamespace(flowchart_source="database"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Remove the disposable database and exports after smoke server shutdown."""
    try:
        yield
    finally:
        engine.dispose()
        store.cleanup()


app = FastAPI(lifespan=lifespan)
app.include_router(flowchart.router)


@app.get("/api/config")
def config() -> dict:
    """Choose the disposable editable source for the standalone smoke page."""
    return {"flowchart_source": "database"}


@app.get("/api/assets/catalog")
def catalog() -> dict:
    """Keep browser tests independent of downloaded TFT catalogs and images."""
    return {"patch": None, "set_number": None, "units": [], "items": [], "augments": []}


build = ROOT / "app/frontend/dist"
app.mount("/assets", StaticFiles(directory=build / "assets"), name="assets")


@app.get("/{path:path}")
def index(path: str) -> FileResponse:
    """Serve the built frontend for standalone routes without starting live services."""
    return FileResponse(build / "index.html")
