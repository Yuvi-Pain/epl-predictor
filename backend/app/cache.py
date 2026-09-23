"""Cache-aside for API responses in Redis.

On each request: look the key up in Redis; on a hit return the stored JSON; on
a miss build the response, store it with a TTL, and return it.

Keys contain everything the response depends on, including the model and data
versions, so new data or a new model is looked up under new keys and never
served from old entries. Nothing ever has to be deleted: old entries become
unreachable and expire on their TTL.

Redis is an optimisation, not a dependency. If it is down, every request is a
miss that is built from Postgres as if there were no cache, and a warning is
logged when Redis first fails (and an info line when it comes back). After a
failure Redis is not tried again for RETRY_AFTER, so an outage costs requests
nothing instead of a connection timeout each.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta

from pydantic import BaseModel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.responses import Response

from app.db import redis_client

log = logging.getLogger(__name__)

# Bump when the stored format changes (e.g. a response schema), so new code
# never reads entries written by old code.
KEY_PREFIX = "epl:v1"

# The versioned keys already keep responses correct, so TTLs only decide how
# long unused entries occupy memory. See the README for the reasoning.
TEAMS_TTL = timedelta(hours=24)
MATCHES_TTL = timedelta(hours=6)
PREDICT_TTL = timedelta(hours=1)

CACHE_HEADER = "X-Cache"
RETRY_AFTER = timedelta(seconds=30)


def cache_key(*parts: object) -> str:
    """Join key parts with ':' under KEY_PREFIX, e.g. epl:v1:teams:d42."""
    return ":".join([KEY_PREFIX, *map(str, parts)])


class ResponseCache:
    """Stores serialised JSON responses in Redis and never raises on Redis errors."""

    def __init__(
        self,
        redis: Redis,
        retry_after: timedelta = RETRY_AFTER,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._redis = redis
        self._retry_after = retry_after.total_seconds()
        self._clock = clock
        self._available = True
        self._retry_at = 0.0

    async def get(self, key: str) -> bytes | None:
        """The stored response, or None on a miss or if Redis is unreachable."""
        if self._skipping():
            return None
        try:
            value: bytes | None = await self._redis.get(key)
        except (RedisError, OSError) as exc:
            self._mark_unavailable(exc)
            return None
        self._mark_available()
        return value

    async def set(self, key: str, value: bytes, ttl: timedelta) -> None:
        """Store a response for `ttl`. Does nothing if Redis is unreachable."""
        if self._skipping():
            return
        try:
            await self._redis.set(key, value, ex=ttl)
        except (RedisError, OSError) as exc:
            self._mark_unavailable(exc)
            return
        self._mark_available()

    async def get_or_build(
        self, key: str, ttl: timedelta, build: Callable[[], Awaitable[BaseModel]]
    ) -> Response:
        """Cache-aside: return the cached JSON for `key`, or build, store and return it.

        The response carries `X-Cache: HIT` or `X-Cache: MISS`. Exceptions from
        `build` (e.g. an HTTPException for a 404) propagate and nothing is stored,
        so errors are never cached.
        """
        if (cached := await self.get(key)) is not None:
            return _json_response(cached, "HIT")
        body = (await build()).model_dump_json().encode()
        await self.set(key, body, ttl)
        return _json_response(body, "MISS")

    def _skipping(self) -> bool:
        """True while Redis recently failed; it is tried again once RETRY_AFTER passes."""
        return not self._available and self._clock() < self._retry_at

    def _mark_unavailable(self, exc: Exception) -> None:
        # Warn once per outage rather than on every request.
        if self._available:
            log.warning(
                "Redis unavailable, serving uncached responses (retrying every %.0fs): %s",
                self._retry_after,
                exc,
            )
        self._available = False
        self._retry_at = self._clock() + self._retry_after

    def _mark_available(self) -> None:
        if not self._available:
            log.info("Redis reachable again, caching resumed")
        self._available = True


def _json_response(body: bytes, status: str) -> Response:
    return Response(body, media_type="application/json", headers={CACHE_HEADER: status})


response_cache = ResponseCache(redis_client)


def get_cache() -> ResponseCache:
    """FastAPI dependency; tests override it with a cache over a fake Redis."""
    return response_cache
