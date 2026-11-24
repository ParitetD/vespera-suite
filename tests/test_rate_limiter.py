"""Тесты RateLimiter: защита от нуля, работа в параллели."""

import asyncio

from app.core.rate_limiter import RateLimiter


def test_rate_limiter_zero_rate_does_not_crash():
    limiter = RateLimiter(default_rate=0)
    asyncio.run(limiter.acquire("example.com"))


def test_rate_limiter_negative_rate_does_not_crash():
    limiter = RateLimiter(default_rate=-5)
    asyncio.run(limiter.acquire("example.com"))


def test_rate_limiter_acquire_multiple_ok():
    limiter = RateLimiter(default_rate=100)
    asyncio.run(limiter.acquire("a.example.com"))
    asyncio.run(limiter.acquire("a.example.com"))
    asyncio.run(limiter.acquire("b.example.com", rate=50))


def test_rate_limiter_parallel_does_not_deadlock():
    limiter = RateLimiter(default_rate=50)

    async def worker(i):
        await limiter.acquire("shared.example.com")
        return i

    async def run():
        return await asyncio.wait_for(asyncio.gather(*[worker(i) for i in range(10)]), timeout=10)

    assert asyncio.run(run()) == list(range(10))
