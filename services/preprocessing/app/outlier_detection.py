"""تشخیص و حذف داده‌های پرت با روش IQR یا Z-Score (FR-PRE-01)."""
from __future__ import annotations

import numpy as np


def is_outlier_zscore(value: float, history: list[float], threshold: float = 3.0) -> bool:
    """تشخیص پرت بودن مقدار جدید نسبت به تاریخچه اخیر با روش Z-Score."""
    if len(history) < 5:
        return False
    arr = np.asarray(history, dtype=float)
    mean, std = arr.mean(), arr.std()
    if std == 0:
        return False
    z = abs((value - mean) / std)
    return z > threshold


def is_outlier_iqr(value: float, history: list[float], k: float = 1.5) -> bool:
    """تشخیص پرت بودن مقدار جدید نسبت به تاریخچه اخیر با روش IQR."""
    if len(history) < 5:
        return False
    arr = np.asarray(history, dtype=float)
    q1, q3 = np.percentile(arr, [25, 75])
    iqr = q3 - q1
    if iqr == 0:
        return False
    lower_bound = q1 - k * iqr
    upper_bound = q3 + k * iqr
    return value < lower_bound or value > upper_bound


def correct_outlier(value: float, history: list[float]) -> float:
    """در صورت تشخیص پرت، مقدار با میانگین تاریخچه اخیر جایگزین می‌شود."""
    if not history:
        return value
    return float(np.mean(history[-5:]))
