"""Offline contracts for local asset lookup, fallback, invalidation, and serving."""

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from core.models import CDragonSet
from services.assets import service
from services.assets.models import AssetCatalog, AssetResolveRequest
from services.assets.utils import image_path


@pytest.fixture
def asset_root(tmp_path, monkeypatch):
    """Isolate every downloaded bundle from the checkout and real network."""
    monkeypatch.setattr(service, "ASSET_ROOT", tmp_path)
    return tmp_path


def bundle(root, patch="17.1", set_number=17, name="Ashe", api="TFT17_Ashe", status="downloaded"):
    """Write a small valid local bundle with a name/ID pair and shared icon bytes."""
    folder = root / patch / f"set-{set_number}" / "en_us"
    (folder / "files").mkdir(parents=True, exist_ok=True)
    (folder / "files" / "unit.png").write_bytes(b"image bytes")
    selected = CDragonSet.model_validate({
        "number": set_number,
        "champions": [{"apiName": api, "name": name}],
        "traits": [{"apiName": "TFT17_Sniper", "name": "Sniper"}],
    })
    catalog = AssetCatalog(patch=patch, locale="en_us", selected_set=selected, items=[
        {"apiName": "TFT_Item_Blade", "name": "Blade"},
    ])
    (folder / "catalog.json").write_text(catalog.model_dump_json())
    manifest = {"patch": patch, "set": set_number, "locale": "en_us", "assets": [
        {"group": group, "api_name": identity, "variant": variant,
         "file": "files/unit.png", "status": status}
        for group, identity, variant in [
            ("portraits", api, "square"), ("items", "TFT_Item_Blade", "icon"),
            ("traits", "TFT17_Sniper", "icon"),
        ]
    ]}
    (folder / "manifest-items-portraits-traits.json").write_text(json.dumps(manifest))
    return folder


def resolve(*names, patch="17.1", set_number=17):
    """Run the public service for portrait requests without loading any database."""
    return service.resolve_assets(AssetResolveRequest(
        patch=patch, set_number=set_number,
        entities=[{"kind": "unit", "name_or_id": name, "role": "portrait"} for name in names],
    )).results


def test_names_ids_and_kinds_share_existing_resolver(asset_root, monkeypatch):
    """Use bidirectional normalized lookup and preserve per-request result ordering."""
    from utils.tft import TFTNameResolver

    def no_network(*args, **kwargs):
        """Fail if runtime resolution attempts to construct an upstream client."""
        raise AssertionError("Asset lookup must remain local")

    monkeypatch.setattr(TFTNameResolver, "from_latest", no_network)
    bundle(asset_root)
    by_name, by_id, unknown = resolve("a s h e", "TFT17_Ashe", "Unknown")
    assert by_name == by_id
    assert by_name.status == "resolved" and not by_name.fallback
    assert unknown.status == "missing" and unknown.src is None
    result = service.resolve_assets(AssetResolveRequest(patch="17.1", set_number=17, entities=[
        {"kind": "item", "name_or_id": "blade", "role": "icon"},
        {"kind": "trait", "name_or_id": "TFT17_Sniper", "role": "icon"},
    ]))
    assert [r.api_name for r in result.results] == ["TFT_Item_Blade", "TFT17_Sniper"]


def test_fallback_order_and_set_isolation(asset_root):
    """Prefer exact, then latest, then numeric patch order, never another set."""
    bundle(asset_root, "17.9")
    bundle(asset_root, "17.10")
    bundle(asset_root, "latest", set_number=18)
    assert resolve("Ashe", patch="fixture")[0].asset_patch == "17.10"
    bundle(asset_root, "latest")
    assert resolve("Ashe")[0].asset_patch == "latest"
    bundle(asset_root)
    assert resolve("Ashe")[0].asset_patch == "17.1"
    assert resolve("Ashe", set_number=19)[0].status == "missing"


def test_partial_bundle_uses_available_same_set_image(asset_root):
    """Skip failed references and files deleted after the manifest was cached."""
    folder = bundle(asset_root)
    bundle(asset_root, "17.2")
    assert resolve("Ashe")[0].asset_patch == "17.1"
    (folder / "files/unit.png").unlink()
    assert resolve("Ashe")[0].asset_patch == "17.2"
    bundle(asset_root, "latest", status="failed")
    assert resolve("Ashe")[0].asset_patch == "17.2"


def test_catalog_and_manifest_revisions_invalidate_cache(asset_root):
    """Reload changed aliases and availability without restarting the backend."""
    folder = bundle(asset_root)
    assert resolve("Ashe")[0].status == "resolved"
    path = folder / "catalog.json"
    data = json.loads(path.read_text())
    data["selected_set"]["champions"][0]["name"] = "New Name"
    path.write_text(json.dumps(data))
    assert resolve("Ashe", "New Name")[0].status == "missing"
    assert resolve("New Name")[0].status == "resolved"
    path = folder / "manifest-items-portraits-traits.json"
    data = json.loads(path.read_text())
    data["assets"][0]["status"] = "failed"
    path.write_text(json.dumps(data))
    assert resolve("New Name")[0].status == "missing"


def test_legacy_invalid_and_unsafe_bundles_are_missing(asset_root, tmp_path):
    """Reject missing metadata, traversal, outside symlinks, and invalid catalogs."""
    folder = bundle(asset_root)
    (folder / "catalog.json").unlink()
    assert resolve("Ashe")[0].status == "missing"
    bundle(asset_root)
    path = folder / "manifest-items-portraits-traits.json"
    data = json.loads(path.read_text())
    data["assets"][0]["file"] = "files/../../outside.png"
    path.write_text(json.dumps(data))
    assert resolve("Ashe")[0].status == "missing"
    assert image_path(folder, "../en_us/files/unit.png") is None
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    (folder / "files/link.png").symlink_to(outside)
    assert image_path(folder, "files/link.png") is None
    (folder / "catalog.json").write_text("not json")
    assert resolve("Ashe")[0].status == "missing"


def test_api_bounds_and_image_http_behavior(asset_root, monkeypatch):
    """Serve conditional images, reject invalid batches, and never return SPA HTML."""
    import api.app as api_app

    folder = bundle(asset_root)
    frontend = asset_root / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("app html")
    monkeypatch.setattr(api_app, "STATIC_DIR", frontend)
    # No lifespan: this test must not warm or mutate any application database.
    client = TestClient(api_app.create_app())
    body = {"patch": "17.1", "set_number": 17, "entities": [
        {"kind": "unit", "name_or_id": "Ashe", "role": "portrait"},
    ]}
    response = client.post("/api/assets/resolve", json=body)
    assert response.status_code == 200
    src = response.json()["results"][0]["src"]
    image = client.get(src)
    assert image.status_code == 200 and image.content == b"image bytes"
    assert image.headers["cache-control"] == "no-cache"
    assert client.get(src, headers={"If-None-Match": image.headers["etag"]}).status_code == 304
    for path in ["/media/tft/missing.png", "/media/tft/17.1/set-17/en_us/catalog.json"]:
        missing = client.get(path, headers={"Accept": "text/html"})
        assert missing.status_code == 404 and missing.text != "app html"
    assert client.post("/api/assets/resolve", json={**body, "patch": "../bad"}).status_code == 422
    assert client.post("/api/assets/resolve", json={**body, "entities": body["entities"] * 257}).status_code == 422
    body["entities"][0]["role"] = "icon"
    assert client.post("/api/assets/resolve", json=body).status_code == 422
    (folder / "files/unit.png").unlink()
    assert client.get(src).status_code == 404


def test_media_root_can_be_absent(tmp_path, monkeypatch):
    """Starting the app without downloads must leave media requests as ordinary 404s."""
    import api.app as api_app

    monkeypatch.setattr(service, "ASSET_ROOT", tmp_path / "not-downloaded")
    client = TestClient(api_app.create_app())
    assert client.get("/media/tft/no.png", headers={"Accept": "text/html"}).status_code == 404


def test_existing_float_set_directory_resolves(asset_root):
    """Accept the existing downloader's CDragon float-formatted set directory."""
    folder = bundle(asset_root)
    folder.parent.rename(folder.parent.with_name("set-17.0"))
    result = resolve("Ashe")[0]
    assert result.status == "resolved" and "/set-17.0/" in result.src


def augment_bundle(root, patch="17.1"):
    """Extend the fixture bundle with a recipe, a consumable, an augment, and its manifest."""
    folder = bundle(root, patch=patch)
    selected = CDragonSet.model_validate({
        "number": 17,
        "champions": [
            {"apiName": "TFT17_Ashe", "name": "Ashe", "cost": 2, "traits": ["Sniper"]},
            {"apiName": "TFT17_Summon", "name": "Summon", "cost": 8},
        ],
        "traits": [{"apiName": "TFT17_Sniper", "name": "Sniper"}],
        "items": ["TFT_Item_InfinityEdge", "TFT17_Consumable_Reroll"],
        "augments": ["TFT17_Augment_Heroic"],
    })
    catalog = AssetCatalog(patch=patch, locale="en_us", selected_set=selected, items=[
        {"apiName": "TFT_Item_BFSword", "name": "B.F. Sword"},
        {"apiName": "TFT_Item_SparringGloves", "name": "Sparring Gloves"},
        {"apiName": "TFT_Item_InfinityEdge", "name": "Infinity Edge",
         "composition": ["TFT_Item_BFSword", "TFT_Item_SparringGloves"]},
        {"apiName": "TFT17_Consumable_Reroll", "name": "Reroll Token"},
        {"apiName": "TFT17_Augment_Heroic", "name": "Heroic Grab Bag"},
    ])
    (folder / "catalog.json").write_text(catalog.model_dump_json())
    (folder / "manifest-augments.json").write_text(json.dumps({
        "patch": patch, "set": 17, "locale": "en_us", "assets": [
            {"group": "augments", "api_name": "TFT17_Augment_Heroic", "variant": "icon",
             "file": "files/unit.png", "status": "downloaded"},
        ],
    }))
    return folder


def test_augments_resolve_only_within_the_set_augment_list(asset_root):
    """Augment lookups reuse item names but never match ordinary items."""
    augment_bundle(asset_root)
    heroic, item = service.resolve_assets(AssetResolveRequest(patch="17.1", set_number=17, entities=[
        {"kind": "augment", "name_or_id": "heroic grab bag", "role": "icon"},
        {"kind": "augment", "name_or_id": "Infinity Edge", "role": "icon"},
    ])).results
    assert heroic.status == "resolved" and heroic.api_name == "TFT17_Augment_Heroic"
    assert item.status == "missing" and item.api_name is None


def test_entity_catalog_lists_draggable_entities(asset_root):
    """The sidebar catalog lists shop units, plannable items, and augments with images."""
    import api.app as api_app

    augment_bundle(asset_root)
    client = TestClient(api_app.create_app())
    response = client.get("/api/assets/catalog", params={"patch": "17.1", "set_number": 17})
    assert response.status_code == 200
    body = response.json()
    assert [u["api_name"] for u in body["units"]] == ["TFT17_Ashe"]
    assert body["units"][0]["cost"] == 2 and body["units"][0]["src"].startswith("/media/tft/")
    items = {i["api_name"]: i for i in body["items"]}
    assert set(items) == {"TFT_Item_BFSword", "TFT_Item_SparringGloves", "TFT_Item_InfinityEdge"}
    assert items["TFT_Item_InfinityEdge"]["type"] == "craftable" and items["TFT_Item_BFSword"]["type"] == "component"
    # Only Blade has a downloaded item icon in the fixture; the rest render as text tiles.
    assert items["TFT_Item_InfinityEdge"]["src"] is None
    assert body["augments"] == [{
        "api_name": "TFT17_Augment_Heroic", "name": "Heroic Grab Bag",
        "src": body["augments"][0]["src"],
    }] and body["augments"][0]["src"]
    empty = client.get("/api/assets/catalog", params={"set_number": 5}).json()
    assert empty["units"] == empty["items"] == empty["augments"] == []
    assert client.get("/api/assets/catalog", params={"patch": "../x"}).status_code == 422
