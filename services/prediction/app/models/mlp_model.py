"""MLP model (a light scikit-learn neural network) as an LSTM alternative without TensorFlow.

Used for systematic comparison with XGBoost in environments where TensorFlow is not installed.
If TensorFlow is available, the pipeline also runs the real LSTM training.
"""
from __future__ import annotations

import numpy as np
from sklearn.neural_network import MLPRegressor

from .base import BaseTemperaturePredictor


class MLPTemperaturePredictor(BaseTemperaturePredictor):
    name = "mlp_reactor_temp"

    def __init__(self, n_lags: int = 10, hidden_layer_sizes: tuple[int, ...] = (64, 32), max_iter: int = 300):
        self.n_lags = n_lags
        self._model = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            activation="relu",
            solver="adam",
            learning_rate_init=0.001,
            max_iter=max_iter,
            random_state=42,
            early_stopping=True,
            validation_fraction=0.1,
        )
        self._is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self._model.fit(X, y)
        self._is_fitted = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("The model has not been trained yet; call fit first.")
        return self._model.predict(X)

    def predict_from_history(self, history: list[float]) -> float:
        features = self.build_lag_features(history, self.n_lags)
        return float(self.predict(features)[0])
