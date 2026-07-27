"""قیود ایمنی سخت (Hard Constraints) برای بهینه‌سازی فرایند (فاز ۴).

هیچ توصیه‌ای که این قیود را نقض کند نباید به اپراتور ارائه شود.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessBounds:
    """محدوده فیزیکی و ایمنی متغیرهای کنترلی."""

    reactor_temp_min: float = 150.0
    reactor_temp_max: float = 350.0
    reactor_temp_safe_min: float = 180.0  # محدوده عملیاتی ایمن‌تر از فیزیکی
    reactor_temp_safe_max: float = 320.0
    pressure_min: float = 10.0
    pressure_max: float = 40.0
    pressure_safe_min: float = 15.0
    pressure_safe_max: float = 35.0
    feed_flow_min: float = 100.0
    feed_flow_max: float = 500.0
    feed_flow_safe_min: float = 150.0
    feed_flow_safe_max: float = 450.0
    # حداکثر تغییر مجاز در یک توصیه (نرخ تغییر ایمن)
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
    """بررسی قیود سخت؛ لیست خالی یعنی نقطه عملیاتی مجاز است."""
    violations: list[ConstraintViolation] = []

    if not (bounds.reactor_temp_safe_min <= reactor_temp_c <= bounds.reactor_temp_safe_max):
        violations.append(
            ConstraintViolation(
                "temp_safe_envelope",
                f"دما {reactor_temp_c} خارج از محدوده ایمن "
                f"[{bounds.reactor_temp_safe_min}, {bounds.reactor_temp_safe_max}]",
            )
        )
    if not (bounds.pressure_safe_min <= pressure_bar <= bounds.pressure_safe_max):
        violations.append(
            ConstraintViolation(
                "pressure_safe_envelope",
                f"فشار {pressure_bar} خارج از محدوده ایمن "
                f"[{bounds.pressure_safe_min}, {bounds.pressure_safe_max}]",
            )
        )
    if not (bounds.feed_flow_safe_min <= feed_flow_m3h <= bounds.feed_flow_safe_max):
        violations.append(
            ConstraintViolation(
                "feed_safe_envelope",
                f"دبی {feed_flow_m3h} خارج از محدوده ایمن "
                f"[{bounds.feed_flow_safe_min}, {bounds.feed_flow_safe_max}]",
            )
        )

    # قید ترکیبی ایمنی: فشار بالا + دمای بالا خطرناک است
    if pressure_bar > 32.0 and reactor_temp_c > 300.0:
        violations.append(
            ConstraintViolation(
                "high_p_high_t",
                f"ترکیب فشار بالا ({pressure_bar}) و دمای بالا ({reactor_temp_c}) مجاز نیست",
            )
        )

    # قید نرخ تغییر نسبت به وضعیت فعلی
    if current_feed_flow is not None and abs(feed_flow_m3h - current_feed_flow) > bounds.max_feed_delta:
        violations.append(
            ConstraintViolation(
                "feed_rate_of_change",
                f"تغییر دبی {abs(feed_flow_m3h - current_feed_flow):.1f} از حد مجاز "
                f"{bounds.max_feed_delta} بیشتر است",
            )
        )
    if current_pressure_bar is not None and abs(pressure_bar - current_pressure_bar) > bounds.max_pressure_delta:
        violations.append(
            ConstraintViolation(
                "pressure_rate_of_change",
                f"تغییر فشار {abs(pressure_bar - current_pressure_bar):.1f} از حد مجاز "
                f"{bounds.max_pressure_delta} بیشتر است",
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
    """برش نقطه پیشنهادی به محدوده ایمن و نرخ تغییر مجاز."""
    p = max(bounds.pressure_safe_min, min(bounds.pressure_safe_max, pressure_bar))
    f = max(bounds.feed_flow_safe_min, min(bounds.feed_flow_safe_max, feed_flow_m3h))
    p = max(current_pressure_bar - bounds.max_pressure_delta, min(current_pressure_bar + bounds.max_pressure_delta, p))
    f = max(current_feed_flow - bounds.max_feed_delta, min(current_feed_flow + bounds.max_feed_delta, f))
    return p, f
