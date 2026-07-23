"""اینترفیس مشترک مدل‌های پیش‌بینی دمای راکتور (FR-ML-01)."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseTemperaturePredictor(ABC):
    name: str = "base"

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """آموزش مدل روی توالی‌های تاریخچه (X) و مقدار هدف ۶۰ ثانیه بعد (y)."""

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """پیش‌بینی دمای راکتور برای افق زمانی تعیین‌شده."""

    @staticmethod
    def build_lag_features(history: list[float], n_lags: int = 10) -> np.ndarray:
        """ساخت ویژگی از n مقدار آخر تاریخچه (Lag Features)."""
        if len(history) < n_lags:
            padded = [history[0]] * (n_lags - len(history)) + list(history) if history else [0.0] * n_lags
        else:
            padded = history[-n_lags:]
        return np.asarray(padded, dtype=float).reshape(1, -1)
