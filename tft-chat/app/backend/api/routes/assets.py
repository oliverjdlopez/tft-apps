"""Read-only local entity images and bounded catalog lookup routes."""

from pathlib import Path

from typing import Annotated

from fastapi import APIRouter, Query
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles

from core.config import load_config
from services.assets import service
from services.assets.models import AssetResolveRequest, AssetResolveResponse, EntityCatalogResponse
from services.assets.utils import image_path

router = APIRouter(prefix="/api/assets")


@router.post("/resolve", response_model=AssetResolveResponse)
def resolve(request: AssetResolveRequest) -> AssetResolveResponse:
    """Resolve a batch off the event loop without contacting upstream services."""
    return service.resolve_assets(request)


@router.get("/catalog", response_model=EntityCatalogResponse)
def catalog(
    patch: Annotated[str | None, Query(max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")] = None,
    set_number: Annotated[int | None, Query(ge=1, le=99)] = None,
) -> EntityCatalogResponse:
    """List draggable Flowchart sidebar entities from local downloads only.

    Without an explicit set, the configured ``[chat] set_number`` is used, then
    the newest downloaded set.
    """
    return service.list_catalog(patch, set_number or load_config().chat.set_number)


class EntityMedia(StaticFiles):
    """Serve only local images, including when downloads are initially absent."""

    async def check_config(self) -> None:
        """Allow a missing download directory; individual image requests return 404."""

    async def get_response(self, path: str, scope):
        """Preserve conditional file responses while excluding metadata and traversal."""
        if image_path(Path(self.directory), path) is None:
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        # The downloader can overwrite URL-hashed filenames, so always revalidate.
        response.headers["Cache-Control"] = "no-cache"
        return response
