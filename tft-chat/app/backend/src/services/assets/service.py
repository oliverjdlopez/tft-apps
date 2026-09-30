"""Batch image resolution over existing local Community Dragon downloads."""

from pathlib import Path

from constants import ItemTypes
from .models import (
    AssetResolveRequest,
    AssetResolveResponse,
    CatalogAugment,
    CatalogItem,
    CatalogUnit,
    EntityCatalogResponse,
    EntityImageResult,
)
from .utils import (
    bundle_candidates,
    canonical_api_name,
    catalog_item_ids,
    image_src,
    latest_set_number,
    load_bundle,
)

ASSET_ROOT = Path(__file__).resolve().parents[5] / "app" / "static" / "cdragon"
IMAGE_VARIANTS = {
    "unit": ("portraits", "square"),
    "item": ("items", "icon"),
    "trait": ("traits", "icon"),
    "augment": ("augments", "icon"),
}
# Consumables, armory keys, and other bespoke entries are not plannable items.
HIDDEN_ITEM_TYPES = {ItemTypes.UNKNOWN, ItemTypes.SPECIAL}


def resolve_assets(request: AssetResolveRequest) -> AssetResolveResponse:
    """Resolve names or IDs through downloaded catalogs, falling back within a set.

    Args:
        request: Bounded patch/set batch of unit, item, trait, and augment image requests.

    Returns:
        Ordered image results with explicit missing and fallback metadata.
    """
    bundles = [
        (directory, bundle)
        for directory in bundle_candidates(ASSET_ROOT, request.patch, request.set_number)
        if (bundle := load_bundle(ASSET_ROOT, directory, request.set_number)) is not None
    ]
    results = []
    for entity in request.entities:
        result = EntityImageResult(status="missing")
        group, variant = IMAGE_VARIANTS[entity.kind]
        for directory, bundle in bundles:
            canonical = canonical_api_name(bundle, entity.kind, entity.name_or_id)
            if canonical is None:
                continue
            result.api_name = result.api_name or canonical
            src = image_src(ASSET_ROOT, directory, bundle, group, canonical, variant)
            if src is None:
                continue
            patch = directory.parent.parent.name
            result = EntityImageResult(
                status="resolved", api_name=canonical, src=src,
                asset_patch=patch, fallback=patch != request.patch,
            )
            break
        results.append(result)
    return AssetResolveResponse(results=results)


def list_catalog(patch: str | None, set_number: int | None) -> EntityCatalogResponse:
    """List draggable units, items, and augments for the Flowchart sidebar.

    The roster comes from the first valid bundle in the same fallback order as
    :func:`resolve_assets`; each image falls back through later bundles of the
    same set, so a partially downloaded patch still shows older icons.

    Args:
        patch: Requested patch folder, or ``None`` for ``latest``.
        set_number: TFT set whose roster is listed, or ``None`` for the
            newest downloaded set.

    Returns:
        Sorted entity lists; empty when no bundle for the set is downloaded.
    """
    set_number = set_number or latest_set_number(ASSET_ROOT)
    if set_number is None:
        return EntityCatalogResponse(patch=patch, set_number=None, units=[], items=[], augments=[])
    bundles = [
        (directory, bundle)
        for directory in bundle_candidates(ASSET_ROOT, patch or "latest", set_number)
        if (bundle := load_bundle(ASSET_ROOT, directory, set_number)) is not None
        and bundle.catalog is not None
    ]
    if not bundles:
        return EntityCatalogResponse(patch=patch, set_number=set_number, units=[], items=[], augments=[])
    primary = bundles[0][1]
    resolver = primary.resolver

    def src(kind: str, api_name: str) -> str | None:
        """Find the first downloaded image for an entity across fallback bundles."""
        group, variant = IMAGE_VARIANTS[kind]
        return next(
            (s for d, b in bundles if (s := image_src(ASSET_ROOT, d, b, group, api_name, variant))),
            None,
        )

    units = [
        CatalogUnit(api_name=c.apiName, name=c.name or c.apiName, cost=c.cost, src=src("unit", c.apiName))
        for c in primary.catalog.selected_set.champions
        # Only shop champions: summons, golems, and armory keys have no traits.
        if c.apiName and c.traits and c.cost in range(1, 6)
    ]
    items = []
    for api_name in catalog_item_ids(primary.catalog):
        item_type = resolver.classify_item(api_name)
        if item_type in HIDDEN_ITEM_TYPES or resolver.item(api_name) is None:
            continue
        items.append(CatalogItem(
            api_name=api_name, name=resolver.item_name(api_name),
            # classify_item returns None for basic recipe components.
            type=str(item_type) if item_type else "component", src=src("item", api_name),
        ))
    augments = [
        CatalogAugment(api_name=api_name, name=resolver.item_name(api_name), src=src("augment", api_name))
        for api_name in sorted(primary.augments)
        if resolver.item(api_name) is not None
    ]
    return EntityCatalogResponse(
        patch=patch, set_number=set_number,
        units=sorted(units, key=lambda u: (u.cost, u.name)),
        items=sorted(items, key=lambda i: (i.type, i.name)),
        augments=sorted(augments, key=lambda a: a.name),
    )
