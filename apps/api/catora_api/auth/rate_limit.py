from __future__ import annotations

import redis.asyncio as redis


class RateLimitExceeded(Exception):
    pass


class RedisRateLimiter:
    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    async def check(self, key: str, limit: int, window_seconds: int) -> None:
        client = redis.from_url(  # type: ignore[no-untyped-call]
            self._redis_url, decode_responses=True
        )
        try:
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, window_seconds)
            if count > limit:
                raise RateLimitExceeded
        finally:
            await client.aclose()
