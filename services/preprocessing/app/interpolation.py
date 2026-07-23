"""درون‌یابی خطی برای جایگزینی مقادیر ازدست‌رفته (NaN) - FR-PRE-02."""
from __future__ import annotations

import math

import pandas as pd


def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def interpolate_series(history: list[float | None]) -> list[float]:
    """درون‌یابی خطی روی یک سری زمانی که ممکن است شامل مقادیر None/NaN باشد."""
    series = pd.Series(history, dtype="float64")
    interpolated = series.interpolate(method="linear", limit_direction="both")
    return interpolated.tolist()


def interpolate_last_value(history: list[float | None], fallback: float) -> float:
    """اگر آخرین مقدار گم‌شده باشد، بر اساس تاریخچه نزدیک آن را درون‌یابی می‌کند."""
    cleaned = interpolate_series(history)
    if cleaned and not math.isnan(cleaned[-1]):
        return cleaned[-1]
    return fallback
