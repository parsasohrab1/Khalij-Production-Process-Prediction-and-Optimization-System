"""مدل LSTM جایگزین برای پیش‌بینی دمای راکتور (FR-ML-01).

TensorFlow به‌صورت پیش‌فرض در requirements.txt نصب نمی‌شود (برای سبک نگه‌داشتن
ایمیج پیش‌فرض که XGBoost را استفاده می‌کند). برای فعال‌سازی LSTM:
    pip install tensorflow==2.16.1
و سپس `PREDICTION_MODEL_TYPE=lstm` را در .env تنظیم کنید.
"""
from __future__ import annotations

import numpy as np

from .base import BaseTemperaturePredictor


class LSTMTemperaturePredictor(BaseTemperaturePredictor):
    name = "lstm_reactor_temp"

    def __init__(self, n_lags: int = 10, units: int = 32, epochs: int = 20):
        try:
            import tensorflow as tf  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "TensorFlow نصب نشده است. برای استفاده از مدل LSTM: pip install tensorflow==2.16.1"
            ) from exc

        from tensorflow import keras
        from tensorflow.keras import layers

        self.n_lags = n_lags
        self.epochs = epochs
        self._model = keras.Sequential(
            [
                layers.Input(shape=(n_lags, 1)),
                layers.LSTM(units, activation="tanh"),
                layers.Dense(1),
            ]
        )
        self._model.compile(optimizer="adam", loss="mse")
        self._is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        X_reshaped = X.reshape((X.shape[0], X.shape[1], 1))
        self._model.fit(X_reshaped, y, epochs=self.epochs, verbose=0)
        self._is_fitted = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("مدل هنوز آموزش داده نشده است؛ ابتدا fit را صدا بزنید.")
        X_reshaped = X.reshape((X.shape[0], X.shape[1], 1))
        return self._model.predict(X_reshaped, verbose=0).flatten()

    def predict_from_history(self, history: list[float]) -> float:
        features = self.build_lag_features(history, self.n_lags)
        return float(self.predict(features)[0])
