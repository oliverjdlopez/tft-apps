"""Riot API routing values.

Riot splits its endpoints across *platform* hosts (per-shard, e.g. `na1`) and
*regional* hosts (aggregated, e.g. `americas`). Match-V1 and Account-V1 use
regional routing; League-V1, Summoner-V1, Spectator-V5 and Status-V1 use
platform routing.
"""

from __future__ import annotations

PLATFORMS: set[str] = {
    "na1", "br1", "lan", "las", "oc1",
    "kr", "jp1",
    "euw1", "eune1", "tr1", "ru", "me1",
    "vn2", "tw2", "sg2", "th2", "ph2",
}

REGIONS: set[str] = {"americas", "asia", "europe", "sea"}

PLATFORM_TO_REGION: dict[str, str] = {
    "na1": "americas", "br1": "americas", "lan": "americas", "las": "americas", "oc1": "americas",
    "euw1": "europe", "eune1": "europe", "tr1": "europe", "ru": "europe", "me1": "europe",
    "kr": "asia", "jp1": "asia",
    "vn2": "sea", "tw2": "sea", "sg2": "sea", "th2": "sea", "ph2": "sea",
}


def platform_host(platform: str) -> str:
    p = platform.lower()
    if p not in PLATFORMS:
        raise ValueError(
            f"Unknown platform {platform!r}. Expected one of: {sorted(PLATFORMS)}"
        )
    return f"{p}.api.riotgames.com"


def region_host(region: str) -> str:
    r = region.lower()
    if r not in REGIONS:
        raise ValueError(
            f"Unknown region {region!r}. Expected one of: {sorted(REGIONS)}"
        )
    return f"{r}.api.riotgames.com"
