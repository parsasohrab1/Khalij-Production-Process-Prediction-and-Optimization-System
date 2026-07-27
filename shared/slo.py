"""کمک‌کننده SLO/Uptime برای NFR-PER-02 (فاز ۸).

هدف: ۹۹.۹۹٪ uptime ≈ حداکثر ~۰.۶ دقیقه downtime در هفته / ~۴.۳ دقیقه در ماه.
"""
from __future__ import annotations

from dataclasses import dataclass


# ثانیه در بازه‌های زمانی
SECONDS_PER_DAY = 86400
SECONDS_PER_WEEK = 7 * SECONDS_PER_DAY
SECONDS_PER_MONTH = 30 * SECONDS_PER_DAY


@dataclass(frozen=True)
class SloTarget:
    name: str
    objective: float  # e.g. 0.9999
    window_seconds: int

    @property
    def error_budget_seconds(self) -> float:
        return (1.0 - self.objective) * self.window_seconds

    def remaining_budget_seconds(self, downtime_seconds: float) -> float:
        return max(0.0, self.error_budget_seconds - downtime_seconds)

    def burn_ratio(self, downtime_seconds: float) -> float:
        budget = self.error_budget_seconds
        if budget <= 0:
            return 0.0
        return downtime_seconds / budget

    def as_dict(self, downtime_seconds: float = 0.0) -> dict:
        return {
            "name": self.name,
            "objective": self.objective,
            "objective_percent": round(self.objective * 100, 4),
            "window_seconds": self.window_seconds,
            "error_budget_seconds": round(self.error_budget_seconds, 3),
            "downtime_seconds": round(downtime_seconds, 3),
            "remaining_budget_seconds": round(self.remaining_budget_seconds(downtime_seconds), 3),
            "burn_ratio": round(self.burn_ratio(downtime_seconds), 4),
            "slo_met": downtime_seconds <= self.error_budget_seconds,
        }


NFR_PER_02_WEEKLY = SloTarget("nfr-per-02-weekly", 0.9999, SECONDS_PER_WEEK)
NFR_PER_02_MONTHLY = SloTarget("nfr-per-02-monthly", 0.9999, SECONDS_PER_MONTH)


def availability_from_checks(success: int, total: int) -> float:
    if total <= 0:
        return 1.0
    return success / total
