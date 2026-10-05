"""Simple Circuit Breaker for connecting to hardware sources (OPC-UA/Modbus).

When the number of consecutive errors exceeds the threshold, the circuit "opens" and instead of
continuously trying to connect (which could put pressure on a real DCS/PLC), for
the `recovery_timeout` period no attempt is made and the service temporarily switches to
Fallback mode (e.g., simulator). After this period, a trial attempt
(Half-Open) is made.
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
    """Raised when the circuit is open and a new request is not allowed."""


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
                logger.info("Circuit '%s' entered Half-Open state; one trial attempt is allowed.", self.name)
        return self._state

    def allow_request(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        if self._state != CircuitState.CLOSED:
            logger.info("Circuit '%s' returned to Closed state after a successful connection.", self.name)
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._state == CircuitState.HALF_OPEN or self._consecutive_failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "Circuit '%s' opened (%d consecutive errors); switching to Fallback mode for %.0f seconds.",
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
