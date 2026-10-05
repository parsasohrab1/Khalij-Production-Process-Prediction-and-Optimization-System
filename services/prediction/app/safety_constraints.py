"""Hard Constraints for process optimization (phase 4).

No recommendation that violates these constraints should be presented to the operator.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessBounds:
    """Physical and safety range of the control variables."""

    reactor_temp_min: float = 150.0
    reactor_temp_max: float = 350.0
    reactor_temp_safe_min: float = 180.0  # safer operating range than the physical one
    reactor_temp_safe_max: float = 320.0
    pressure_min: float = 10.0
    pressure_max: float = 40.0
    pressure_safe_min: float = 15.0
    pressure_safe_max: float = 35.0
    feed_flow_min: float = 100.0
    feed_flow_max: float = 500.0
    feed_flow_safe_min: float = 150.0
    feed_flow_safe_max: float = 450.0
    # maximum allowed change in one recommendation (safe rate of change)
    max_feed_delta: float = 80.0
    max_pressure_delta: float = 5.0


DEFAULT_BOUNDS = ProcessBounds()


@dataclass
class ConstraintViolation:
    name: str
    detail: str
    severity: str = "hard"  # hard | soft


def check_hard_constraints(
    *,
    reactor_temp_c: float,
    pressure_bar: float,
    feed_flow_m3h: float,
    current_pressure_bar: float | None = None,
    current_feed_flow: float | None = None,
    bounds: ProcessBounds = DEFAULT_BOUNDS,
) -> list[ConstraintViolation]:
    """Check the hard constraints; an empty list means the operating point is allowed."""
    violations: list[ConstraintViolation] = []

    if not (bounds.reactor_temp_safe_min <= reactor_temp_c <= bounds.reactor_temp_safe_max):
        violations.append(
            ConstraintViolation(
                "temp_safe_envelope",
                f"Temperature {reactor_temp_c} is outside the safe range "
                f"[{bounds.reactor_temp_safe_min}, {bounds.reactor_temp_safe_max}]",
            )
        )
    if not (bounds.pressure_safe_min <= pressure_bar <= bounds.pressure_safe_max):
        violations.append(
            ConstraintViolation(
                "pressure_safe_envelope",
                f"Pressure {pressure_bar} is outside the safe range "
                f"[{bounds.pressure_safe_min}, {bounds.pressure_safe_max}]",
            )
        )
    if not (bounds.feed_flow_safe_min <= feed_flow_m3h <= bounds.feed_flow_safe_max):
        violations.append(
            ConstraintViolation(
                "feed_safe_envelope",
                f"Flow {feed_flow_m3h} is outside the safe range "
                f"[{bounds.feed_flow_safe_min}, {bounds.feed_flow_safe_max}]",
            )
        )

    # safety combined constraint: high pressure + high temperature is dangerous
    if pressure_bar > 32.0 and reactor_temp_c > 300.0:
        violations.append(
            ConstraintViolation(
                "high_p_high_t",
                f"The combination of high pressure ({pressure_bar}) and high temperature ({reactor_temp_c}) is not allowed",
            )
        )

    # rate-of-change constraint relative to the current state
    if current_feed_flow is not None and abs(feed_flow_m3h - current_feed_flow) > bounds.max_feed_delta:
        violations.append(
            ConstraintViolation(
                "feed_rate_of_change",
                f"Flow change {abs(feed_flow_m3h - current_feed_flow):.1f} exceeds the allowed limit "
                f"{bounds.max_feed_delta}",
            )
        )
    if current_pressure_bar is not None and abs(pressure_bar - current_pressure_bar) > bounds.max_pressure_delta:
        violations.append(
            ConstraintViolation(
                "pressure_rate_of_change",
                f"Pressure change {abs(pressure_bar - current_pressure_bar):.1f} exceeds the allowed limit "
                f"{bounds.max_pressure_delta}",
            )
        )

    return violations


def is_feasible(
    *,
    reactor_temp_c: float,
    pressure_bar: float,
    feed_flow_m3h: float,
    current_pressure_bar: float | None = None,
    current_feed_flow: float | None = None,
    bounds: ProcessBounds = DEFAULT_BOUNDS,
) -> bool:
    return (
        len(
            check_hard_constraints(
                reactor_temp_c=reactor_temp_c,
                pressure_bar=pressure_bar,
                feed_flow_m3h=feed_flow_m3h,
                current_pressure_bar=current_pressure_bar,
                current_feed_flow=current_feed_flow,
                bounds=bounds,
            )
        )
        == 0
    )


def clip_to_safe(
    *,
    pressure_bar: float,
    feed_flow_m3h: float,
    current_pressure_bar: float,
    current_feed_flow: float,
    bounds: ProcessBounds = DEFAULT_BOUNDS,
) -> tuple[float, float]:
    """Clip the proposed point to the safe range and the allowed rate of change."""
    p = max(bounds.pressure_safe_min, min(bounds.pressure_safe_max, pressure_bar))
    f = max(bounds.feed_flow_safe_min, min(bounds.feed_flow_safe_max, feed_flow_m3h))
    p = max(current_pressure_bar - bounds.max_pressure_delta, min(current_pressure_bar + bounds.max_pressure_delta, p))
    f = max(current_feed_flow - bounds.max_feed_delta, min(current_feed_flow + bounds.max_feed_delta, f))
    return p, f
