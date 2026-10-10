"""Offline contracts for container HTTP routing and service selection."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


ENTRYPOINT = Path(__file__).resolve().parents[1] / "backend.py"
SPEC = spec_from_file_location("suite_container_backend", ENTRYPOINT)
backend = module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


@pytest.fixture
def frontend(tmp_path):
    """Build minimal public files next to a private file outside the web root."""
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>VOD app</html>")
    (root / "assets/app.js").write_text("export const app = true;")
    (tmp_path / "private.txt").write_text("private-token")
    (root / "escape.txt").symlink_to(tmp_path / "private.txt")
    return root


def test_vod_frontend_preserves_api_routes_and_html_navigation(frontend):
    """Serve public assets and deep links without replacing real API responses."""
    app = FastAPI()

    @app.get("/api/health")
    def health():
        """Represent the VOD API already registered before frontend mounting."""
        return {"ok": True}

    backend.mount_vod_frontend(app, frontend)
    client = TestClient(app)
    assert client.get("/").text == "<html>VOD app</html>"
    assert client.get("/review/current", headers={"Accept": "text/html"}).text == "<html>VOD app</html>"
    assert client.get("/assets/app.js").text == "export const app = true;"
    assert client.head("/assets/app.js").status_code == 200
    assert client.get("/api/health").json() == {"ok": True}


@pytest.mark.parametrize("path", [
    "/api", "/api/missing", "/assets/missing.js", "/escape.txt",
    "/%2e%2e/private.txt", "/unknown.json",
])
def test_vod_frontend_does_not_mask_missing_api_or_serve_private_paths(frontend, path):
    """Preserve 404 semantics for API/asset misses and reject traversal/symlinks."""
    app = FastAPI()
    backend.mount_vod_frontend(app, frontend)
    response = TestClient(app).get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "private-token" not in response.text and "VOD app" not in response.text


def test_vod_missing_build_and_non_html_requests_are_explicit(tmp_path):
    """Report missing image output without turning non-HTML misses into pages."""
    app = FastAPI()
    backend.mount_vod_frontend(app, tmp_path / "missing")
    client = TestClient(app)
    assert client.get("/").status_code == 503
    assert client.get("/review/current", headers={"Accept": "application/json"}).status_code == 404


@pytest.mark.parametrize("service,module_name,folder", [
    ("chat", "api.app", "tft-chat"), ("vod", "backend.app", "vod-review"),
])
def test_service_selection_preserves_lifespan_and_desktop_identity(monkeypatch, tmp_path, service, module_name, folder):
    """Import the intended source root and wrap ownership without loading real apps."""
    from contextlib import asynccontextmanager

    events = []

    @asynccontextmanager
    async def lifespan(application):
        """Record normal app startup/shutdown through the identity wrapper."""
        events.append("start")
        yield
        events.append("stop")

    app = FastAPI(lifespan=lifespan)
    imported = []

    def import_app(name):
        """Substitute only the selected app import while preserving its identity."""
        imported.append(name)
        return SimpleNamespace(app=app)

    root = tmp_path / folder
    root.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(backend, "import_module", import_app)
    monkeypatch.setenv("CHATTFT_DESKTOP_IDENTITY", "test-container-launch")
    application = backend.load_application(service, tmp_path)
    assert imported == [module_name]
    assert Path.cwd() == root
    with TestClient(application) as client:
        response = client.get("/__chattft_desktop__/identity")
        assert response.headers["x-chattft-desktop-identity"] == "test-container-launch"
    assert events == ["start", "stop"]
