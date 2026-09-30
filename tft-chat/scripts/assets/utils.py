"""Catalogue selection and file helpers for downloading static assets."""

import hashlib
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from core.models import CDragonData, CDragonSet
from scripts.assets.models import Asset

# ============================================================================
# Asset download CLI
#
# Keep upstream path normalization and bundle selection separate from network
# orchestration so catalogue changes can be verified without live downloads.
# ============================================================================

GROUPS = ("portraits", "artwork", "abilities", "traits", "items", "augments")


def safe_segment(value: str) -> str:
    """Validate a CLI path segment before using it in URLs and output folders."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value):
        raise ValueError(f"Invalid path segment: {value!r}")
    return value


def asset_url(path: str, patch: str) -> str:
    """Resolve a TFT game asset reference to its exported Community Dragon image."""
    normalized = path.replace("\\", "/").lower().lstrip("/")
    if any(part in (".", "..") for part in normalized.split("/")):
        raise ValueError(f"Invalid asset path: {path!r}")
    if normalized.startswith("lol-game-data/assets/"):
        normalized = "plugins/rcp-be-lol-game-data/global/default/" + normalized.removeprefix("lol-game-data/assets/")
    elif normalized.startswith("assets/"):
        normalized = "game/" + normalized
    elif not normalized.startswith("game/assets/"):
        raise ValueError(f"Unsupported asset path: {path!r}")
    # Game texture references use engine extensions; CDragon exports PNGs.
    if PurePosixPath(normalized).suffix in (".tex", ".dds"):
        normalized = str(PurePosixPath(normalized).with_suffix(".png"))
    return f"https://raw.communitydragon.org/{safe_segment(patch)}/{quote(normalized, safe='/')}"


def select_assets(data: CDragonData, selected: CDragonSet, groups: list[str], patch: str) -> list[Asset]:
    """Build set-scoped image records for the download manifest.

    Args:
        data: Complete catalogue containing shared item and augment records.
        selected: Set whose champion, trait, item, and augment IDs are included.
        groups: Image categories requested by the CLI.
        patch: Community Dragon version used for image URLs.

    Returns:
        Image references including recursive item recipe dependencies.
    """
    references: list[tuple[str, str, str, str | None]] = []
    for champion in selected.champions:
        references.extend([
            ("portraits", champion.apiName, "square", champion.squareIcon),
            ("artwork", champion.apiName, "icon", champion.icon),
            ("artwork", champion.apiName, "tile", champion.tileIcon),
            ("abilities", champion.apiName, "ability", champion.ability.icon if champion.ability else None),
        ])
    references.extend(("traits", trait.apiName, "icon", trait.icon) for trait in selected.traits)
    items = {item.apiName: item for item in data.items}
    wanted = set(selected.items)
    pending = list(wanted)
    # Components may be omitted from set.items but are needed for recipe displays.
    while pending:
        item = items.get(pending.pop())
        if item:
            for component in item.composition:
                if component not in wanted:
                    wanted.add(component)
                    pending.append(component)
    for group, identifiers in (("items", wanted), ("augments", set(selected.augments))):
        for identifier in sorted(identifiers):
            item = items.get(identifier)
            if item:
                references.append((group, identifier, "icon", item.icon))
    # Pick names from the entire set so shared images keep the same destination
    # even when separate invocations request different groups.
    names: dict[str, tuple[str, str]] = {}
    for _, identifier, variant, path in references:
        if path and path.strip() and path.strip().casefold() != "none":
            try:
                key = asset_url(path.strip(), patch)
            except ValueError:
                # Invalid paths only fail a run when their group is requested.
                continue
            candidate = (identifier, variant)
            names[key] = min(names.get(key, candidate), candidate)
    assets = []
    for group, identifier, variant, path in references:
        if group not in groups or not path:
            continue
        # Some catalogue entries encode a missing texture as the string "None"
        # rather than JSON null. Treat that marker like an absent icon.
        path = path.strip()
        if not path or path.casefold() == "none":
            continue
        url = asset_url(path, patch)
        identifier_for_file, variant_for_file = names[url]
        filename = descriptive_filename(identifier_for_file, variant_for_file, url)
        assets.append(Asset(group, identifier, variant, url, f"files/{filename}"))
    return assets


def descriptive_filename(identifier: str, variant: str, url: str) -> str:
    """Name an image using catalogue identity with a stable collision suffix.

    Args:
        identifier: Canonical API ID chosen for the shared image.
        variant: Image role, such as square, tile, or ability.
        url: Source URL used to distinguish otherwise identical safe names.

    Returns:
        A bounded, filesystem-safe filename with the source image extension.
    """
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{identifier}-{variant}").strip("-_")
    stem = stem[:140] or "asset"
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    return f"{stem}--{digest}{PurePosixPath(url).suffix}"


def write_atomic(path: Path, content: bytes) -> None:
    """Replace a download or manifest only after its contents are fully written."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".download-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
