"""Command-line operations for downloading existing CDragon image fields."""

import argparse
import asyncio
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import httpx

from core.cdragon import CDragon
from services.assets.models import AssetCatalog
from scripts.assets.models import Asset
from scripts.assets.utils import GROUPS, safe_segment, select_assets, write_atomic

STATIC_ROOT = Path(__file__).resolve().parents[2] / "app" / "static"


def build_parser() -> argparse.ArgumentParser:
    """Build the standalone downloader's catalogue and transfer options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patch", default="latest", help="CDragon patch (default: latest)")
    parser.add_argument("--locale", default="en_us", help="Catalogue locale (default: en_us)")
    parser.add_argument("--set", dest="set_number", type=int, help="TFT set; defaults to the existing client's configured selection")
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    parser.add_argument("--folder", default="cdragon", help="Folder name within app/static (default: cdragon)")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=30, help="Per-request timeout in seconds")
    parser.add_argument("--overwrite", action="store_true", help="Download existing files again")
    return parser


async def download_asset(client: httpx.AsyncClient, asset: Asset, root: Path, semaphore: asyncio.Semaphore, overwrite: bool) -> str:
    """Download one image atomically for the bundle manifest.

    Args:
        client: Shared HTTP transport with the configured request timeout.
        asset: Source URL and relative destination for this image.
        root: Selected patch/set bundle directory.
        semaphore: Bound on simultaneous image transfers.
        overwrite: Whether existing files should be refreshed.

    Returns:
        The manifest status, either downloaded or cached.

    Raises:
        httpx.HTTPError: The image request failed.
        ValueError: The server did not return a nonempty image.
    """
    destination = root / asset.file
    async with semaphore:
        if destination.is_file() and destination.stat().st_size and not overwrite:
            return "cached"
        # Reuse downloads made before descriptive filenames were introduced.
        # Preserve old files because earlier manifests may still reference them.
        legacy = root / "files" / (hashlib.sha256(asset.url.encode()).hexdigest() + destination.suffix)
        if legacy.is_file() and legacy.stat().st_size and not overwrite:
            write_atomic(destination, legacy.read_bytes())
            return "cached"
        response = await client.get(asset.url)
        response.raise_for_status()
        if not response.headers.get("content-type", "").lower().startswith("image/") or not response.content:
            raise ValueError(f"Expected a nonempty image at {asset.url}")
        write_atomic(destination, response.content)
        return "downloaded"


async def download_bundle(args: argparse.Namespace) -> int:
    """Fetch a set catalogue, download unique images, and record successes and failures."""
    cdragon = CDragon(patch=args.patch, locale=args.locale)
    try:
        # Both operations share the existing client's catalogue cache.
        selected = await cdragon.current_set(args.set_number)
        data = await cdragon.raw()
    finally:
        await cdragon.aclose()
    set_label = safe_segment(str(selected.number))
    root = STATIC_ROOT / args.folder / args.patch / f"set-{set_label}" / args.locale
    # Save the exact resolver inputs once; UI lookups must never fetch CDragon.
    catalog = AssetCatalog(
        patch=args.patch, locale=args.locale, selected_set=selected, items=data.items,
    )
    write_atomic(root / "catalog.json", catalog.model_dump_json(indent=2).encode())
    assets = select_assets(data, selected, args.groups, args.patch)
    if not assets:
        raise ValueError("No image references found for the selected set and groups")
    unique = {asset.url: asset for asset in assets}
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=args.timeout, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(download_asset(client, asset, root, semaphore, args.overwrite) for asset in unique.values()),
            return_exceptions=True,
        )
    statuses = dict(zip(unique, results))
    records = []
    for asset in assets:
        status = statuses[asset.url]
        record = asdict(asset)
        record["status"] = "failed" if isinstance(status, BaseException) else status
        if isinstance(status, BaseException):
            record["error"] = str(status)
        records.append(record)
    # Each manifest describes one requested group selection; disjoint runs retain
    # their manifests while sharing the same downloaded files.
    manifest = root / ("manifest-" + "-".join(sorted(set(args.groups))) + ".json")
    write_atomic(manifest, json.dumps({
        "patch": args.patch, "locale": args.locale, "set": selected.number,
        "groups": sorted(set(args.groups)), "assets": records,
    }, indent=2).encode())
    failures = sum(isinstance(result, BaseException) for result in results)
    print(f"{len(unique) - failures}/{len(unique)} images available; {failures} failed. Manifest: {manifest}")
    return 1 if failures else 0


def main() -> int:
    """Validate CLI arguments and return a nonzero exit code for incomplete bundles."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        for value in (args.patch, args.locale, args.folder):
            safe_segment(value)
        if args.concurrency < 1 or not 0 < args.timeout < float("inf"):
            raise ValueError("Concurrency and timeout must be positive and finite")
        return asyncio.run(download_bundle(args))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        parser.exit(1, f"Download failed: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
