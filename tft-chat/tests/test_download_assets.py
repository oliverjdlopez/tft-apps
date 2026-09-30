"""Offline coverage for catalogue scoping and asset download failures."""

import asyncio
import json

import httpx
import pytest

from core.models import CDragonData
from scripts.assets import main as downloader
from scripts.assets.models import Asset
from scripts.assets.utils import asset_url, safe_segment, select_assets


def catalogue() -> CDragonData:
    """Build two sets with shared images and a cyclic component recipe."""
    return CDragonData.model_validate({
        "items": [
            {"apiName": "item", "icon": "ASSETS/item.tex", "composition": ["component"]},
            {"apiName": "component", "icon": "ASSETS/component.dds", "composition": ["item"]},
            {"apiName": "augment", "icon": "ASSETS/augment.tex"},
            {"apiName": "other", "icon": "ASSETS/other.tex"},
        ],
        "setData": [{
            "number": 17, "items": ["item"], "augments": ["augment"],
            "champions": [{"apiName": "unit", "squareIcon": "ASSETS/unit.tex", "tileIcon": "ASSETS/unit.tex"}],
            "traits": [{"apiName": "trait", "icon": "ASSETS/trait.tex"}],
        }],
    })


@pytest.mark.parametrize("missing", [None, "", "None", " none ", "NONE", "   "])
def test_missing_image_markers_do_not_abort_bundle(missing: str | None) -> None:
    """Skip missing textures across groups while retaining valid item images."""
    data = catalogue()
    selected = data.set_data[0]
    selected.champions[0].squareIcon = missing
    selected.traits[0].icon = missing
    data.items[0].icon = missing
    assets = select_assets(data, selected, ["portraits", "traits", "items"], "latest")
    assert [(asset.group, asset.api_name) for asset in assets] == [("items", "component")]


def test_bundle_scoping_and_shared_images() -> None:
    """Keep unrelated items out, include components, and retain shared references."""
    data = catalogue()
    assets = select_assets(data, data.set_data[0], ["items", "augments", "portraits", "artwork"], "16.1")
    assert {asset.api_name for asset in assets} == {"item", "component", "augment", "unit"}
    units = [asset for asset in assets if asset.api_name == "unit"]
    assert len(units) == 2
    assert units[0].file == units[1].file
    assert all("/16.1/" in asset.url for asset in assets)


@pytest.mark.parametrize("path", ["ASSETS/Icons/Test.tex", "ASSETS/Icons/Test.dds", "game/assets/icons/test.png"])
def test_game_texture_paths(path: str) -> None:
    """Map game texture references to the patch's exported PNG location."""
    assert asset_url(path, "16.1") == "https://raw.communitydragon.org/16.1/game/assets/icons/test.png"


def test_path_validation() -> None:
    """Reject traversal and arbitrary hosts while supporting client asset paths."""
    for value in ("..", "../elsewhere", "/tmp", "a/b"):
        with pytest.raises(ValueError):
            safe_segment(value)
    for path in ("ASSETS/../secret.tex", "https://example.com/image.png"):
        with pytest.raises(ValueError):
            asset_url(path, "latest")
    assert "/plugins/rcp-be-lol-game-data/global/default/assets/icon.png" in asset_url(
        "/lol-game-data/assets/ASSETS/Icon.png", "latest"
    )


def test_failed_download_preserves_existing_file(tmp_path) -> None:
    """An unsuccessful forced refresh must leave the prior local image intact."""
    asset = Asset("items", "item", "icon", "https://example.com/icon.png", "files/icon.png")
    destination = tmp_path / asset.file
    destination.parent.mkdir()
    destination.write_bytes(b"prior image")

    async def run() -> None:
        """Exercise a failed refresh followed by cache reuse with a mock transport."""
        def respond(request: httpx.Request) -> httpx.Response:
            """Return a server failure without contacting an upstream service."""
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(httpx.HTTPStatusError):
                await downloader.download_asset(client, asset, tmp_path, asyncio.Semaphore(1), True)
            assert await downloader.download_asset(client, asset, tmp_path, asyncio.Semaphore(1), False) == "cached"

    asyncio.run(run())
    assert destination.read_bytes() == b"prior image"


def test_bundle_manifest_records_partial_failure(tmp_path, monkeypatch) -> None:
    """Deduplicate transfers and record per-reference status when an image is missing."""
    data = catalogue()

    class FakeCDragon:
        """Supply the existing client contract without network or configuration."""

        def __init__(self, **kwargs):
            """Accept the downloader's unchanged client constructor options."""

        async def current_set(self, number):
            """Return the test catalogue's selected set."""
            return data.set_data[0]

        async def raw(self):
            """Return the complete test catalogue."""
            return data

        async def aclose(self):
            """Match the existing client's lifecycle contract."""

    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        """Serve images except for one missing augment."""
        requests.append(str(request.url))
        if "augment" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=b"test image")

    original_client = httpx.AsyncClient

    def client(**kwargs):
        """Inject an offline transport into the downloader's HTTP client."""
        return original_client(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(downloader, "CDragon", FakeCDragon)
    monkeypatch.setattr(downloader, "STATIC_ROOT", tmp_path)
    monkeypatch.setattr(downloader.httpx, "AsyncClient", client)
    args = downloader.build_parser().parse_args(["--set", "17"])
    assert asyncio.run(downloader.download_bundle(args)) == 1
    manifest = json.loads(next(tmp_path.rglob("manifest-*.json")).read_text())
    from services.assets.models import AssetCatalog
    from utils.tft import TFTNameResolver

    snapshot = AssetCatalog.model_validate_json(next(tmp_path.rglob("catalog.json")).read_text())
    assert snapshot.patch == "latest" and snapshot.selected_set.number == 17
    resolver = TFTNameResolver.from_set(snapshot.selected_set, snapshot.items)
    assert resolver.unit_api_name("unit") == "unit"
    assert resolver.item_api_name("component") == "component"
    assert len(requests) == len(set(requests)) == 5
    assert sum(record["status"] == "failed" for record in manifest["assets"]) == 1
    assert len(list(tmp_path.rglob("files/*.png"))) == 4


def test_descriptive_names_are_stable_across_group_selections() -> None:
    """Keep shared image names readable and stable across aliases and group choices."""
    data = catalogue()
    selected = data.set_data[0]
    selected.champions[0].squareIcon = "ASSETS/unit.dds"
    portraits = select_assets(data, selected, ["portraits"], "latest")
    artwork = select_assets(data, selected, ["artwork"], "latest")
    assert portraits[0].file == artwork[0].file
    assert portraits[0].file.startswith("files/unit-square--")


def test_descriptive_names_handle_unsafe_ids_and_collisions() -> None:
    """Bound unsafe names and distinguish different sources with matching identities."""
    from scripts.assets.utils import descriptive_filename

    first = descriptive_filename("../Unsafe/Name" * 30, "icon", "https://example.com/a.png")
    second = descriptive_filename("../Unsafe/Name" * 30, "icon", "https://example.com/b.png")
    assert first != second
    assert "/" not in first and ".." not in first
    assert len(first) < 200


def test_legacy_download_is_reused_with_descriptive_name(tmp_path) -> None:
    """Copy an old hash-named download without a network request or deleting it."""
    import hashlib

    asset = Asset("items", "item", "icon", "https://example.com/icon.png", "files/item-icon--abc.png")
    legacy = tmp_path / "files" / (hashlib.sha256(asset.url.encode()).hexdigest() + ".png")
    legacy.parent.mkdir()
    legacy.write_bytes(b"existing image")

    async def run() -> None:
        """Verify legacy cache reuse with an HTTP transport that rejects requests."""
        def respond(request: httpx.Request) -> httpx.Response:
            """Fail if cache migration attempts a network request."""
            raise AssertionError("Unexpected network request")

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            assert await downloader.download_asset(client, asset, tmp_path, asyncio.Semaphore(1), False) == "cached"

    asyncio.run(run())
    assert (tmp_path / asset.file).read_bytes() == legacy.read_bytes() == b"existing image"
