"""Simple in-memory LRU cache for stock data."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class LRUCache:
    """Thread-safe LRU cache with TTL expiry."""

    def __init__(self, max_size: int = 50, ttl: int = 300):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        """Get value if exists and not expired."""
        if key not in self._cache:
            return None
        value, ts = self._cache[key]
        if time.time() - ts > self._ttl:
            del self._cache[key]
            return None
        # move to end (most recently used)
        self._cache.move_to_end(key)
        return value

    def set(self, key: str, value: Any) -> None:
        """Set value, evicting oldest if at capacity."""
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = (value, time.time())
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def invalidate(self, key: str) -> None:
        """Remove a specific key."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()

    def stats(self) -> dict:
        """Return cache statistics."""
        now = time.time()
        valid = sum(1 for _, ts in self._cache.values() if now - ts <= self._ttl)
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl": self._ttl,
            "valid_entries": valid,
        }


# singleton caches
stock_cache = LRUCache(max_size=50, ttl=300)  # 5 min TTL for stock data
news_cache = LRUCache(max_size=100, ttl=3600)  # 1 hour for news
