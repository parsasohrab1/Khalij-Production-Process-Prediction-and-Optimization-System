"""مدل XGBoost برای پیش‌بینی دمای خروجی راکتور طی افق ۶۰ ثانیه (FR-ML-01)."""
from __future__ import annotations

import numpy as np
import xgboost as xgb

from .base import BaseTemperaturePredictor


class XGBoostTemperaturePredictor(BaseTemperaturePredictor):
    name = "xgboost_reactor_temp"

    def __init__(self, n_lags: int = 10, **xgb_params):
        self.n_lags = n_lags
        params = {
            "n_estimators": 200,
            "max_depth": 5,
            "learning_rate": 0.05,
            "objective": "reg:squarederror",
            **xgb_params,
        }
        self._model = xgb.XGBRegressor(**params)
        self._is_fitted = False

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        self._model.fit(X, y)
        self._is_fitted = True

    def predict(self, X: np.ndarray) -> np.ndarray:
        if not self._is_fitted:
            raise RuntimeError("مدل هنوز آموزش داده نشده است؛ ابتدا fit را صدا بزنید.")
        return self._model.predict(X)

    def predict_from_history(self, history: list[float]) -> float:
        features = self.build_lag_features(history, self.n_lags)
        return float(self.predict(features)[0])

    def save(self, path: str) -> None:
        self._model.save_model(path)

    def load(self, path: str) -> None:
        self._model.load_model(path)
        self._is_fitted = True

    @staticmethod
    def build_training_set(series: list[float], n_lags: int = 10, horizon: int = 60) -> tuple[np.ndarray, np.ndarray]:
        """ساخت مجموعه آموزشی (X, y) از یک سری زمانی یک‌بعدی."""
        X, y = [], []
        for i in range(n_lags, len(series) - horizon):
            X.append(series[i - n_lags : i])
            y.append(series[i + horizon])
        return np.asarray(X, dtype=float), np.asarray(y, dtype=float)
