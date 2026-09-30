"""Tests for the pulsefire-backed :class:`core.chat_tft_riot.ChatTftRiotClient` facade.

These drive the real pulsefire ``RiotAPIClient`` middleware stack (JSON
decoding, error mapping, rate limiting) but swap in a fake aiohttp
session so no network is touched. They assert the facade contract chat_tft
depends on: parsed JSON out, :class:`RiotAPIError` on failures, 429 retry with
backoff, and correct pulsefire URL building.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from pulsefire.ratelimiters import RiotAPIRateLimiter

from core.chat_tft_riot import ChatTftRiotClient, RiotAPIError


class FakeResponse:
    def __init__(
        self, status: int, body: Any, headers: dict[str, str] | None = None
    ) -> None:
        self.status = status
        self.reason = {200: "OK", 404: "Not Found", 429: "Too Many Requests"}.get(
            status, "Error"
        )
        self._body = body
        self.headers = headers or {}

    async def json(self, **_kwargs: Any) -> Any:
        return self._body

    async def text(self, **_kwargs: Any) -> str:
        return str(self._body)

    async def read(self) -> bytes:
        return str(self._body).encode()


class FakeSession:
    """Stand-in for ``aiohttp.ClientSession`` that replays canned responses."""

    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = responses
        self.closed = False
        self.requests: list[dict[str, Any]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json: Any = None,
        data: Any = None,
    ) -> FakeResponse:
        self.requests.append({"method": method, "url": url, "headers": headers or {}})
        return self._responses.pop(0)

    async def close(self) -> None:
        self.closed = True


def _make_riot(responses: list[FakeResponse], **kwargs: Any) -> tuple[ChatTftRiotClient, FakeSession]:
    kwargs.setdefault("api_key", "test-key")
    riot = ChatTftRiotClient(limiter=RiotAPIRateLimiter(), **kwargs)
    session = FakeSession(responses)
    riot.session = session  # type: ignore[assignment]
    return riot, session


def test_success_returns_parsed_json() -> None:
    riot, session = _make_riot([FakeResponse(200, {"metadata": {}, "info": {}})])

    result = asyncio.run(riot.get_tft_match_v1_match(region="americas", id="NA1_1"))

    assert result == {"metadata": {}, "info": {}}
    assert len(session.requests) == 1
    assert session.requests[0]["url"] == (
        "https://americas.api.riotgames.com/tft/match/v1/matches/NA1_1"
    )
    assert session.requests[0]["headers"].get("X-Riot-Token") == "test-key"


def test_retries_429_then_returns_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("core.chat_tft_riot.asyncio.sleep", fake_sleep)
    riot, session = _make_riot(
        [
            FakeResponse(429, {"status": {"message": "Rate limit"}}, {"Retry-After": "2"}),
            FakeResponse(200, {"ok": True}),
        ],
        max_retries=1,
        retry_base_seconds=1,
        retry_jitter_seconds=0,
    )

    result = asyncio.run(riot.get_tft_match_v1_match(region="americas", id="NA1_1"))

    assert result == {"ok": True}
    assert len(session.requests) == 2
    assert sleeps == [2]


def test_raises_after_429_retry_budget_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("core.chat_tft_riot.asyncio.sleep", fake_sleep)
    riot, session = _make_riot(
        [
            FakeResponse(429, {"status": {"message": "Rate limit"}}),
            FakeResponse(429, {"status": {"message": "Still limited"}}),
        ],
        max_retries=1,
        retry_base_seconds=1,
        retry_jitter_seconds=0,
    )

    with pytest.raises(RiotAPIError) as exc:
        asyncio.run(riot.get_tft_match_v1_match(region="americas", id="NA1_1"))

    assert exc.value.status == 429
    assert len(session.requests) == 2
    assert sleeps == [1]


def test_4xx_maps_to_riot_api_error_with_body() -> None:
    riot, _session = _make_riot([FakeResponse(404, {"status": {"message": "missing"}})])

    with pytest.raises(RiotAPIError) as exc:
        asyncio.run(riot.get_tft_match_v1_match(region="americas", id="NA1_MISSING"))

    assert exc.value.status == 404
    assert exc.value.body == {"status": {"message": "missing"}}


def test_missing_api_key_raises_without_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep dotenv from repopulating a developer key after the test clears it.
    monkeypatch.setenv("RIOT_API_KEY", "")
    riot, session = _make_riot([FakeResponse(200, {})], api_key=None)

    with pytest.raises(RiotAPIError) as exc:
        asyncio.run(riot.get_tft_match_v1_match(region="americas", id="NA1_1"))

    assert exc.value.status == 401
    assert session.requests == []


@pytest.mark.parametrize(
    ("call", "expected_url"),
    [
        (
            lambda r: r.get_tft_match_v1_match_ids_by_puuid(
                region="americas", puuid="abc", queries={"start": 0, "count": 5}
            ),
            "https://americas.api.riotgames.com"
            "/tft/match/v1/matches/by-puuid/abc/ids?start=0&count=5",
        ),
        (
            lambda r: r.league_top("challenger", "na1"),
            "https://na1.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT",
        ),
    ],
)
def test_endpoints_build_expected_pulsefire_urls(call, expected_url: str) -> None:
    riot, session = _make_riot([FakeResponse(200, [])])

    asyncio.run(call(riot))

    assert session.requests[0]["url"] == expected_url


def test_league_top_rejects_unknown_tier() -> None:
    riot, _session = _make_riot([FakeResponse(200, {})])

    with pytest.raises(ValueError):
        asyncio.run(riot.league_top("diamond", "na1"))
