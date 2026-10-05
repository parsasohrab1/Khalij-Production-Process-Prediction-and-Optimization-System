"""Common interface of the reactor temperature prediction models (FR-ML-01)."""
from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseTemperaturePredictor(ABC):
    name: str = "base"

    @abstractmethod
    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Train the model on history sequences (X) and the target value 60 seconds ahead (y)."""

    @abstractmethod
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predict the reactor temperature for the specified time horizon."""

    @staticmethod
    def build_lag_features(history: list[float], n_lags: int = 10) -> np.ndarray:
        """Build features from the last n values of the history (Lag Features)."""
        if len(history) < n_lags:
            padded = [history[0]] * (n_lags - len(history)) + list(history) if history else [0.0] * n_lags
        else:
            padded = history[-n_lags:]
        return np.asarray(padded, dtype=float).reshape(1, -1)
