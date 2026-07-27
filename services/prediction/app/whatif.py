"""شبیه‌سازی What-if برای اپراتور پیش از اعمال توصیه (فاز ۴).

اپراتور می‌تواند مقادیر پیشنهادی (یا دلخواه) را وارد کند و قبل از اعمال،
راندمان تخمینی، قیود ایمنی، و ریسک را ببیند.
"""
from __future__ import annotations

from .optimizer import estimate_efficiency
from .safety_constraints import DEFAULT_BOUNDS, ProcessBounds, check_hard_constraints


def simulate_whatif(
    *,
    reactor_temp_c: float,
    current_pressure_bar: float,
    current_feed_flow: float,
    proposed_pressure_bar: float,
    proposed_feed_flow: float,
    bounds: ProcessBounds | None = None,
) -> dict:
    """شبیه‌سازی سناریوی پیشنهادی در برابر وضعیت فعلی."""
    bounds = bounds or DEFAULT_BOUNDS

    current_eff = estimate_efficiency(reactor_temp_c, current_pressure_bar, current_feed_flow)
    proposed_eff = estimate_efficiency(reactor_temp_c, proposed_pressure_bar, proposed_feed_flow)
    violations = check_hard_constraints(
        reactor_temp_c=reactor_temp_c,
        pressure_bar=proposed_pressure_bar,
        feed_flow_m3h=proposed_feed_flow,
        current_pressure_bar=current_pressure_bar,
        current_feed_flow=current_feed_flow,
        bounds=bounds,
    )

    # امتیاز ریسک ساده: ۰ امن، ۱ پرریسک
    risk = 0.0
    if violations:
        risk = min(1.0, 0.35 * len(violations))
    # نزدیکی به مرز ایمنی نیز ریسک نرم ایجاد می‌کند
    temp_margin = min(
        reactor_temp_c - bounds.reactor_temp_safe_min,
        bounds.reactor_temp_safe_max - reactor_temp_c,
    )
    if temp_margin < 20:
        risk = min(1.0, risk + (20 - temp_margin) / 40)

    safe_to_apply = len(violations) == 0
    return {
        "current": {
            "reactor_temp_c": round(reactor_temp_c, 2),
            "pressure_bar": round(current_pressure_bar, 2),
            "feed_flow_m3h": round(current_feed_flow, 2),
            "estimated_efficiency": round(current_eff, 2),
        },
        "proposed": {
            "reactor_temp_c": round(reactor_temp_c, 2),
            "pressure_bar": round(proposed_pressure_bar, 2),
            "feed_flow_m3h": round(proposed_feed_flow, 2),
            "estimated_efficiency": round(proposed_eff, 2),
        },
        "delta_efficiency": round(proposed_eff - current_eff, 2),
        "delta_feed_flow": round(proposed_feed_flow - current_feed_flow, 2),
        "delta_pressure": round(proposed_pressure_bar - current_pressure_bar, 2),
        "constraints_satisfied": safe_to_apply,
        "constraint_violations": [{"name": v.name, "detail": v.detail, "severity": v.severity} for v in violations],
        "risk_score": round(risk, 3),
        "recommendation": "apply" if safe_to_apply and proposed_eff >= current_eff else (
            "reject_unsafe" if not safe_to_apply else "no_gain"
        ),
    }
