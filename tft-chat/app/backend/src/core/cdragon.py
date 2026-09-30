"""Community Dragon TFT static-data client backed by pulsefire."""

from __future__ import annotations

import aiohttp

from pulsefire.clients import CDragonClient

from core.cache import TTLCache
from core.config import load_config
from core.models import (
    CDragonChampion,
    CDragonData,
    CDragonItem,
    CDragonSet,
    CDragonTrait,
)

CDRAGON_TFT_DATA_URL = "https://raw.communitydragon.org/latest/cdragon/tft/en_us.json"


class CDragon:
    """Typed TFT facade over pulsefire's Community Dragon client."""

    def __init__(
        self,
        *,
        patch: str = "latest",
        locale: str = "en_us",
        pf_client: CDragonClient | None = None,
        ttl: float = 3600,
    ) -> None:
        self.patch = patch
        self.locale = locale
        self._pf = pf_client or CDragonClient(
            default_params={"patch": patch, "locale": locale}
        )
        self._cache = TTLCache(ttl=ttl)

    async def aclose(self) -> None:
        session = getattr(self._pf, "session", None)
        if session is not None and not session.closed:
            await session.close()
            self._pf.session = None

    async def _ensure_session(self) -> None:
        session = getattr(self._pf, "session", None)
        if session is None or session.closed:
            self._pf.session = aiohttp.ClientSession()

    async def raw(self) -> CDragonData:
        async def fetch() -> CDragonData:
            if isinstance(self._pf, CDragonClient):
                await self._ensure_session()
            data = await self._pf.get_tft_data(
                patch=self.patch,
                locale=self.locale,
            )
            return CDragonData.model_validate(data)

        return await self._cache.get_or_fetch(
            f"cdragon::{self.patch}::{self.locale}",
            fetch,
        )

    async def latest_version(self) -> str:
        """Compatibility name for callers that display the static-data version."""
        return self.patch

    async def all_items(self) -> list[CDragonItem]:
        return (await self.raw()).items

    async def all_sets(self) -> list[CDragonSet]:
        data = await self.raw()
        if data.set_data:
            return data.set_data
        return list(data.sets.values())

    async def current_set(self, set_number: int | None = None) -> CDragonSet:
        effective_set = set_number
        if effective_set is None:
            effective_set = load_config().chat.set_number
        sets = await self.all_sets()
        if not sets:
            raise RuntimeError("Community Dragon returned no TFT sets")
        if effective_set is not None:
            for s in sets:
                if _set_number(s) == float(effective_set):
                    return s
            raise ValueError(f"TFT set {effective_set} not found in Community Dragon data")
        return max(sets, key=_set_number)

    async def champions(self, set_number: int | None = None) -> list[CDragonChampion]:
        return (await self.current_set(set_number)).champions

    async def traits(self, set_number: int | None = None) -> list[CDragonTrait]:
        return (await self.current_set(set_number)).traits


def _set_number(set_obj: CDragonSet) -> float:
    n = set_obj.number
    if isinstance(n, int | float):
        return float(n)
    try:
        return float(str(n))
    except (TypeError, ValueError):
        return -1.0
