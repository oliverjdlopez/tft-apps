"""The official, key-gated, rate-limited Riot TFT API (match and league data).

Requires a developer API key via the ``RIOT_API_KEY`` environment variable;
get one at https://developer.riotgames.com/. :class:`ChatTftRiotClient`
subclasses the `pulsefire <https://pulsefire.iann838.com/>`_ SDK's
``RiotAPIClient`` directly, so every endpoint it defines --
``get_tft_match_v1_match``, ``get_tft_match_v1_match_ids_by_puuid``,
``get_tft_league_v1_challenger_league``, and so on -- is available as-is,
with pulsefire itself owning URL building, HTTP, and the adaptive rate
limiter that self-tunes from Riot's ``X-App-Rate-Limit`` /
``X-Method-Rate-Limit`` response headers.

On top of that, this module adds only what pulsefire doesn't provide: a
required-API-key check, lazy aiohttp session management, and a typed,
body-carrying error (:class:`RiotAPIError`) with 429 retry/backoff that
honors ``Retry-After``.

Community Dragon static TFT data (no key required) lives in :mod:`core.cdragon`
and is attached here as ``ChatTftRiotClient.cdragon``.
"""

from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
import logging
import random
from datetime import datetime, timezone
from typing import Any

import aiohttp
from pulsefire.clients import RiotAPIClient
from pulsefire.middlewares import json_response_middleware, rate_limiter_middleware
from pulsefire.ratelimiters import BaseRateLimiter, RiotAPIRateLimiter

from .config import load_config
from .cdragon import CDragon


logger = logging.getLogger(__name__)


class RiotAPIError(RuntimeError):
    def __init__(self, status: int, message: str, body: Any = None) -> None:
        super().__init__(f"Riot API error {status}: {message}")
        self.status = status
        self.body = body
        # Seconds to wait before retrying, parsed from a 429 ``Retry-After``
        # header when present.
        self.retry_after: float | None = None


def _riot_retry_middleware(
    *,
    max_retries: int,
    base_seconds: float,
    max_seconds: float,
    jitter_seconds: float,
):
    """Replace pulsefire's ``http_error_middleware``.

    Raises ChatTFT's typed :class:`RiotAPIError` (carrying the decoded
    response body) on non-2xx responses instead of
    ``aiohttp.ClientResponseError``, and retries 429s -- honoring
    ``Retry-After`` when present, else exponential backoff -- before giving
    up. pulsefire's own adaptive rate limiter (later in the middleware chain)
    already throttles proactively from rate-limit headers; this only handles
    the 429s that still get through.
    """

    def constructor(next_middleware):
        async def middleware(invocation):
            attempts = max_retries + 1
            for attempt in range(attempts):
                response = await next_middleware(invocation)
                if 200 <= response.status < 300:
                    return response

                try:
                    body: Any = await response.json(content_type=None)
                except Exception:
                    try:
                        body = await response.text()
                    except Exception:
                        body = None
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))

                if response.status != 429 or attempt == attempts - 1:
                    error = RiotAPIError(response.status, response.reason or "", body)
                    error.retry_after = retry_after
                    raise error

                delay = _retry_delay(base_seconds, max_seconds, jitter_seconds, attempt, retry_after)
                logger.warning(
                    "Riot API rate limited request to %s; retrying in %.2fs "
                    "(attempt %d/%d)",
                    invocation.urlformat,
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(delay)

        return middleware

    return constructor


class ChatTftRiotClient(RiotAPIClient):
    """ChatTFT's Riot API client: a thin, mostly-inherited pulsefire facade."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        cdragon: CDragon | None = None,
        limiter: BaseRateLimiter | None = None,
        max_retries: int | None = None,
        retry_base_seconds: float | None = None,
        retry_max_seconds: float | None = None,
        retry_jitter_seconds: float | None = None,
    ) -> None:
        self.api_key = api_key or load_config().secrets.riot_api_key
        self.cdragon = cdragon or CDragon()
        self._session: aiohttp.ClientSession | None = None
        super().__init__(
            default_headers={"X-Riot-Token": self.api_key or ""},
            middlewares=[
                json_response_middleware(),
                _riot_retry_middleware(
                    max_retries=max(0, max_retries if max_retries is not None else 5),
                    base_seconds=max(
                        0.0, retry_base_seconds if retry_base_seconds is not None else 1.0
                    ),
                    max_seconds=max(
                        0.0, retry_max_seconds if retry_max_seconds is not None else 60.0
                    ),
                    jitter_seconds=max(
                        0.0, retry_jitter_seconds if retry_jitter_seconds is not None else 0.25
                    ),
                ),
                rate_limiter_middleware(limiter or RiotAPIRateLimiter()),
            ],
        )

    @property
    def session(self) -> aiohttp.ClientSession | None:
        """Lazily-created aiohttp session; also gates calls on ``RIOT_API_KEY``.

        pulsefire's ``invoke()`` reads ``self.session`` when building each
        request, so this property is the one hook available to enforce both
        checks without overriding every inherited endpoint method.
        """
        if not self.api_key:
            raise RiotAPIError(
                401,
                "Missing RIOT_API_KEY environment variable. "
                "Request a key at https://developer.riotgames.com/",
            )
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    @session.setter
    def session(self, value: aiohttp.ClientSession | None) -> None:
        self._session = value

    async def aclose(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        await self.cdragon.aclose()

    async def league_top(
        self, tier: str, platform: str, queue: str = "RANKED_TFT"
    ) -> dict[str, Any]:
        """Top-tier ladder for ``tier`` (challenger/grandmaster/master).

        pulsefire exposes these as three separate methods with no shared
        entrypoint; this dispatches to the right one.
        """
        league_methods = {
            "challenger": self.get_tft_league_v1_challenger_league,
            "grandmaster": self.get_tft_league_v1_grandmaster_league,
            "master": self.get_tft_league_v1_master_league,
        }
        league_method = league_methods.get(tier.lower())
        if league_method is None:
            raise ValueError("tier must be 'challenger', 'grandmaster', or 'master'")
        return await league_method(region=platform.lower(), queries={"queue": queue})


def _retry_delay(
    base_seconds: float,
    max_seconds: float,
    jitter_seconds: float,
    attempt: int,
    retry_after: float | None,
) -> float:
    backoff = min(max_seconds, base_seconds * (2 ** attempt))
    if retry_after is not None:
        backoff = max(backoff, min(retry_after, max_seconds))
    jitter = random.uniform(0, jitter_seconds)
    return min(max_seconds, backoff + jitter)


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass

    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
