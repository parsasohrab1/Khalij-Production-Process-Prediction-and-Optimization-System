"""Linear interpolation to replace missing values (NaN) - FR-PRE-02."""
from __future__ import annotations

import math

import pandas as pd


def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def interpolate_series(history: list[float | None]) -> list[float]:
    """Linear interpolation on a time series that may contain None/NaN values."""
    series = pd.Series(history, dtype="float64")
    interpolated = series.interpolate(method="linear", limit_direction="both")
    return interpolated.tolist()


def interpolate_last_value(history: list[float | None], fallback: float) -> float:
    """If the last value is missing, interpolates it based on the nearby history."""
    cleaned = interpolate_series(history)
    if cleaned and not math.isnan(cleaned[-1]):
        return cleaned[-1]
    return fallback
