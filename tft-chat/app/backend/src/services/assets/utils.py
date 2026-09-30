"""Filesystem and catalog helpers for local entity image resolution."""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from .models import AssetCatalog, LoadedBundle
from utils.tft import TFTNameResolver

logger = logging.getLogger(__name__)
IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})

# ============================================================================
# Asset service
#
# Catalog metadata is cached; image availability is checked for each batch so
# deleted or incomplete downloads never become successful image references.
# ============================================================================


def image_path(root: Path, relative: str) -> Path | None:
    """Accept only existing image files contained within the local media root."""
    candidate = root / relative
    try:
        resolved = candidate.resolve()
        if (
            Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not resolved.is_relative_to(root.resolve())
            or resolved.suffix.lower() not in IMAGE_SUFFIXES
            or not resolved.is_file()
            or not resolved.stat().st_size
        ):
            return None
        return resolved
    except (OSError, ValueError):
        return None


def bundle_candidates(root: Path, patch: str, set_number: int) -> list[Path]:
    """Order exact, latest, and descending numbered bundles within one TFT set."""
    numbered = sorted(
        (p.name for p in root.glob("*") if re.fullmatch(r"\d+(?:\.\d+)*", p.name)),
        key=lambda name: (tuple(int(part) for part in name.split(".")), name),
        reverse=True,
    )
    patches = dict.fromkeys([patch, "latest", *numbered])
    # CDragon models permit numeric set identifiers; existing downloads commonly
    # serialize the number as 17.0. Retain that layout and accept integer folders.
    return [
        root / patch_name / set_folder / "en_us"
        for patch_name in patches
        for set_folder in (f"set-{set_number}", f"set-{set_number}.0")
    ]


def load_bundle(root: Path, directory: Path, set_number: int) -> LoadedBundle | None:
    """Load contained catalog files using their revision as the cache identity."""
    try:
        paths = [directory / "catalog.json", *sorted(directory.glob("manifest-*.json"))]
        if len(paths) < 2 or any(not p.resolve().is_relative_to(root.resolve()) for p in paths):
            return None
        revision = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in paths)
        return cached_bundle(str(directory), set_number, revision)
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=64)
def cached_bundle(directory: str, set_number: int, revision: tuple) -> LoadedBundle | None:
    """Parse each catalog revision once without network access or DB dependencies."""
    try:
        folder = Path(directory)
        catalog = AssetCatalog.model_validate_json((folder / "catalog.json").read_text())
        patch = folder.parent.parent.name
        if catalog.patch != patch or catalog.locale != "en_us" or catalog.selected_set.number != set_number:
            return None
        files = {}
        conflicts = set()
        for filename, _, _ in revision[1:]:
            manifest = json.loads(Path(filename).read_text())
            if manifest.get("patch") != patch or manifest.get("set") != set_number or manifest.get("locale") != "en_us":
                continue
            for record in manifest.get("assets", []):
                relative = record.get("file", "")
                if (
                    record.get("status") not in {"downloaded", "cached"}
                    or not isinstance(relative, str)
                    or len(Path(relative).parts) != 2
                    or Path(relative).parts[0] != "files"
                ):
                    continue
                key = (record["group"], record["api_name"], record["variant"])
                # Conflicting overlapping manifests must not choose an arbitrary image.
                if key in files and files[key] != relative:
                    conflicts.add(key)
                files[key] = relative
        for key in conflicts:
            files.pop(key, None)
        return LoadedBundle(
            TFTNameResolver.from_set(catalog.selected_set, catalog.items), files,
            augments=frozenset(catalog.selected_set.augments), catalog=catalog,
        )
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        logger.warning("Ignoring invalid local asset bundle %s", directory)
        return None


def canonical_api_name(bundle: LoadedBundle, kind: str, name_or_id: str) -> str | None:
    """Resolve a unit, item, trait, or augment name to its bundle API name.

    Augments are stored alongside items in Community Dragon's global item list,
    so they reuse item lookup but only match the selected set's augment IDs.
    """
    if kind == "augment":
        canonical = bundle.resolver.item_api_name(name_or_id)
        return canonical if canonical in bundle.augments else None
    return getattr(bundle.resolver, f"{kind}_api_name")(name_or_id)


def image_src(root: Path, directory: Path, bundle: LoadedBundle, group: str, api_name: str, variant: str) -> str | None:
    """Return the ``/media/tft`` URL for a downloaded image, or ``None`` when absent."""
    relative = bundle.files.get((group, api_name, variant))
    if relative is None or image_path(directory, relative) is None:
        return None
    return "/media/tft/" + quote((directory / relative).relative_to(root).as_posix(), safe="/")


def catalog_item_ids(catalog: AssetCatalog) -> list[str]:
    """List a set's items plus the recipe components omitted from ``set.items``.

    Matches the downloader's recursive component expansion so every recipe
    component can be dragged, in a stable sorted order.
    """
    items = {item.apiName: item for item in catalog.items}
    wanted = set(catalog.selected_set.items)
    pending = list(wanted)
    while pending:
        item = items.get(pending.pop())
        for component in item.composition if item else ():
            if component not in wanted:
                wanted.add(component)
                pending.append(component)
    return sorted(wanted - set(catalog.selected_set.augments))


def latest_set_number(root: Path) -> int | None:
    """Return the highest set number with any downloaded bundle folder."""
    numbers = [
        int(float(match.group(1)))
        for folder in root.glob("*/set-*")
        if (match := re.fullmatch(r"set-(\d+(?:\.0)?)", folder.name))
    ]
    return max(numbers, default=None)
