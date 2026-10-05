"""Temporary account lockout after failed login attempts (phase 6 / NFR-SEC-01)."""
from __future__ import annotations

import logging

import redis

from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_FAIL_KEY = "auth:fail:{code}"
_LOCK_KEY = "auth:lock:{code}"


class AccountLockout:
    def __init__(
        self,
        redis_url: str | None = None,
        max_failures: int | None = None,
        lockout_seconds: int | None = None,
    ) -> None:
        self._r = redis.from_url(redis_url or settings.redis_url, decode_responses=True)
        self.max_failures = max_failures or settings.login_max_failures
        self.lockout_seconds = lockout_seconds or settings.login_lockout_seconds

    def is_locked(self, employee_code: str) -> tuple[bool, int]:
        """(locked?, seconds_remaining)."""
        key = _LOCK_KEY.format(code=employee_code)
        try:
            ttl = self._r.ttl(key)
            if ttl and ttl > 0:
                return True, int(ttl)
            if self._r.exists(key):
                return True, self.lockout_seconds
            return False, 0
        except Exception:  # noqa: BLE001
            logger.debug("Lockout Redis unavailable.")
            return False, 0

    def register_failure(self, employee_code: str) -> int:
        fail_key = _FAIL_KEY.format(code=employee_code)
        try:
            count = int(self._r.incr(fail_key))
            if count == 1:
                self._r.expire(fail_key, self.lockout_seconds)
            if count >= self.max_failures:
                self._r.setex(_LOCK_KEY.format(code=employee_code), self.lockout_seconds, "1")
                self._r.delete(fail_key)
            return count
        except Exception:  # noqa: BLE001
            return 0

    def clear(self, employee_code: str) -> None:
        try:
            self._r.delete(_FAIL_KEY.format(code=employee_code))
            self._r.delete(_LOCK_KEY.format(code=employee_code))
        except Exception:  # noqa: BLE001
            pass


_lockout = AccountLockout()


def get_lockout() -> AccountLockout:
    return _lockout
