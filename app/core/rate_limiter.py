"""Единый RateLimiter: per-domain token bucket для всех модулей вместе.

Чтобы два модуля, бьющие по одному сайту, не превышали его лимит:
ключ = домен (host). Настраивается через config.
"""

import asyncio
import time
from collections import defaultdict
from typing import Dict, Optional


class TokenBucket:
    __slots__ = ("rate", "capacity", "tokens", "last", "lock")

    def __init__(self, rate_per_sec: float, capacity: float = 1.0):
        # rate <= 0 → защита: минимальная скорость, иначе ZeroDivisionError в acquire()
        self.rate = rate_per_sec if rate_per_sec > 0 else 0.01
        self.capacity = max(capacity, 0.01)
        self.tokens = self.capacity
        self.last = time.monotonic()
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.rate)
                self.last = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class RateLimiter:
    def __init__(self, default_rate: float = 1.0):
        self.default_rate = default_rate if default_rate > 0 else 1.0
        self._buckets: Dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(self.default_rate)
        )

    async def acquire(self, domain: str, rate: Optional[float] = None) -> None:
        key = (domain or "").lower().strip()
        if key not in self._buckets:
            bucket_rate = rate if (rate is not None and rate > 0) else self.default_rate
            self._buckets[key] = TokenBucket(bucket_rate)
        await self._buckets[key].acquire()
