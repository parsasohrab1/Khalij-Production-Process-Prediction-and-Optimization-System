"""Circuit Breaker ساده برای اتصال به منابع سخت‌افزاری (OPC-UA/Modbus).

هنگامی که تعداد خطاهای متوالی از آستانه بگذرد، مدار «باز» می‌شود و به‌جای
تلاش پیوسته برای اتصال (که می‌تواند به DCS/PLC واقعی فشار وارد کند)، برای
مدت `recovery_timeout` هیچ تلاشی صورت نمی‌گیرد و سرویس به‌طور موقت به حالت
Fallback (مثلاً شبیه‌ساز) سوییچ می‌کند. پس از پایان این بازه، یک تلاش آزمایشی
(Half-Open) انجام می‌شود.
"""
from __future__ import annotations

import logging
import time
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """هنگامی که مدار باز است و درخواست جدید مجاز نیست، صادر می‌شود."""


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 3, recovery_timeout_s: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.monotonic() - self._opened_at >= self.recovery_timeout_s:
                self._state = CircuitState.HALF_OPEN
                logger.info("مدار '%s' وارد حالت Half-Open شد؛ یک تلاش آزمایشی مجاز است.", self.name)
        return self._state

    def allow_request(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info("مدار '%s' پس از اتصال موفق به حالت Closed بازگشت.", self.name)
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._state == CircuitState.HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "مدار '%s' باز شد (%d خطای متوالی)؛ برای %.0f ثانیه به حالت Fallback سوییچ می‌شود.",
                self.name,
                self._consecutive_failures,
                self.recovery_timeout_s,
            )

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "consecutive_failures": self._consecutive_failures,
        }
