"""Request rate limiting with Redis (phase 6)."""
from __future__ import annotations

import logging
import time

import redis
from fastapi import HTTPException, Request, status

from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class RateLimiter:
    def __init__(self, redis_url: str | None = None) -> None:
        self._r = redis.from_url(redis_url or settings.redis_url, decode_responses=True)

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        """True if allowed; the second value = the current count in the window."""
        now = int(time.time())
        bucket = f"ratelimit:{key}:{now // window_seconds}"
        try:
            count = self._r.incr(bucket)
            if count == 1:
                self._r.expire(bucket, window_seconds + 1)
            return count <= limit, int(count)
        except Exception:  # noqa: BLE001
            logger.debug("Rate limiter Redis unavailable; allowing request.")
            return True, 0


_limiter = RateLimiter()


def enforce_rate_limit(request: Request, *, scope: str, limit: int, window_seconds: int = 60) -> None:
    client = request.client.host if request.client else "unknown"
    allowed, count = _limiter.hit(f"{scope}:{client}", limit, window_seconds)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Request rate exceeds the allowed limit ({count}/{limit} in {window_seconds}s).",
            headers={"Retry-After": str(window_seconds)},
        )
