"""Local download catalogs and bounded image lookup contracts."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.models import CDragonItem, CDragonSet
from utils.tft import TFTNameResolver

Segment = Annotated[str, Field(max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]


class AssetModel(BaseModel):
    """Reject unexpected fields at catalog and asset API boundaries."""

    model_config = ConfigDict(extra="forbid")


class AssetCatalog(AssetModel):
    """Persist resolver inputs alongside one downloaded patch/set bundle."""

    schema_version: Literal["assets.v1"] = "assets.v1"
    patch: Segment
    locale: Segment
    selected_set: CDragonSet
    items: list[CDragonItem]


class EntityImageRequest(AssetModel):
    """Request a composition or flowchart image using an existing entity name or API ID."""

    kind: Literal["unit", "item", "trait", "augment"]
    name_or_id: Annotated[str, Field(min_length=1, max_length=200)]
    role: Literal["portrait", "icon"]

    @model_validator(mode="after")
    def validate_role(self) -> "EntityImageRequest":
        """Limit image roles to the combinations currently used by compositions."""
        if self.role != ("portrait" if self.kind == "unit" else "icon"):
            raise ValueError("Units require portrait; items, traits, and augments require icon")
        return self


class AssetResolveRequest(AssetModel):
    """Bound one batch of local image lookups to a TFT patch and set."""

    patch: Segment
    set_number: Annotated[int, Field(strict=True, ge=1)]
    entities: Annotated[list[EntityImageRequest], Field(min_length=1, max_length=256)]


class EntityImageResult(AssetModel):
    """Describe image availability in the same order as the input requests."""

    status: Literal["resolved", "missing"]
    api_name: str | None = None
    src: str | None = None
    asset_patch: str | None = None
    fallback: bool = False


class AssetResolveResponse(AssetModel):
    """Return one result per requested entity, including unresolved entries."""

    results: list[EntityImageResult]


class CatalogUnit(AssetModel):
    """List one shop champion as a draggable Flowchart sidebar tile."""

    api_name: str
    name: str
    cost: int
    src: str | None = None


class CatalogItem(AssetModel):
    """List one component or finished item as a draggable Flowchart sidebar tile."""

    api_name: str
    name: str
    type: str
    src: str | None = None


class CatalogAugment(AssetModel):
    """List one set augment as a draggable Flowchart sidebar tile."""

    api_name: str
    name: str
    src: str | None = None


class EntityCatalogResponse(AssetModel):
    """Return the browsable unit, item, and augment roster for one patch and set.

    ``src`` is null for entities whose image has not been downloaded, so the
    browser can render a text tile instead of a broken image.
    """

    patch: str | None
    set_number: int | None
    units: list[CatalogUnit]
    items: list[CatalogItem]
    augments: list[CatalogAugment]


@dataclass(frozen=True)
class LoadedBundle:
    """Cache a local resolver and manifest index without retaining image bytes."""

    resolver: TFTNameResolver
    files: dict[tuple[str, str, str], str]
    augments: frozenset[str] = frozenset()
    catalog: AssetCatalog | None = None
