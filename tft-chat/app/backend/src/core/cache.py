"""Tiny async TTL cache used to avoid hammering upstream static-data services."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    def __init__(self, ttl: float = 3600) -> None:
        self.ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get_or_fetch(self, key: str, fetch: Callable[[], Awaitable[T]]) -> T:
        now = time.time()
        cached = self._store.get(key)
        if cached and now - cached[0] < self.ttl:
            return cached[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._store.get(key)
            if cached and time.time() - cached[0] < self.ttl:
                return cached[1]
            value = await fetch()
            self._store[key] = (time.time(), value)
            return value
