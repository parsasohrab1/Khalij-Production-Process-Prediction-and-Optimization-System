"""Pipeline آموزش batch + backtesting + مقایسه مدل‌ها (فاز ۳).

جریان:
  1. ساخت مجموعه آموزشی از سری زمانی (lag features)
  2. تقسیم زمانی train/test (بدون shuffle — برای جلوگیری از نشت زمانی)
  3. آموزش XGBoost و MLP (و LSTM در صورت وجود TensorFlow)
  4. ارزیابی با MAE/RMSE/MAPE
  5. انتخاب مدل برتر و ثبت در MLflow Model Registry (Staging→Production)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from .drift import DriftDetector
from .metrics import evaluate
from .mlflow_registry import MLflowModelManager
from .models.base import BaseTemperaturePredictor
from .models.mlp_model import MLPTemperaturePredictor
from .models.xgboost_model import XGBoostTemperaturePredictor

logger = logging.getLogger(__name__)


@dataclass
class ModelCandidate:
    name: str
    predictor: BaseTemperaturePredictor
    metrics: dict[str, float]
    run_id: str | None = None


def build_lag_dataset(
    series: list[float] | np.ndarray,
    n_lags: int = 10,
    horizon: int = 60,
) -> tuple[np.ndarray, np.ndarray]:
    return XGBoostTemperaturePredictor.build_training_set(
        list(series), n_lags=n_lags, horizon=horizon
    )


def temporal_train_test_split(
    X: np.ndarray, y: np.ndarray, test_ratio: float = 0.2
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """تقسیم زمانی: آخرین test_ratio برای تست (بدون shuffle)."""
    n = len(X)
    split = max(1, int(n * (1 - test_ratio)))
    if split >= n:
        split = n - 1
    return X[:split], X[split:], y[:split], y[split:]


def _try_build_lstm(n_lags: int, epochs: int = 15) -> BaseTemperaturePredictor | None:
    if os.getenv("PREDICTION_ENABLE_LSTM", "false").lower() not in ("1", "true", "yes"):
        return None
    try:
        from .models.lstm_model import LSTMTemperaturePredictor

        return LSTMTemperaturePredictor(n_lags=n_lags, units=32, epochs=epochs)
    except Exception as exc:  # noqa: BLE001 - TensorFlow/protobuf ممکن است ناسازگار باشد
        logger.info("LSTM در دسترس نیست (%s)؛ مقایسه با XGBoost و MLP ادامه می‌یابد.", exc)
        return None


class TrainingPipeline:
    def __init__(
        self,
        *,
        mlflow_tracking_uri: str,
        n_lags: int = 10,
        horizon: int = 60,
        test_ratio: float = 0.2,
        psi_threshold: float = 0.25,
    ):
        self.n_lags = n_lags
        self.horizon = horizon
        self.test_ratio = test_ratio
        self.mlflow = MLflowModelManager(mlflow_tracking_uri)
        self.drift = DriftDetector(psi_threshold=psi_threshold)
        self.active_model: BaseTemperaturePredictor | None = None
        self.active_model_name: str = "linear_trend_fallback"
        self.active_metrics: dict[str, float] = {}
        self.active_run_id: str | None = None
        self.active_version: str | None = None
        self.last_comparison: list[dict] = []

    def train_and_select(self, series: list[float], promote_to_production: bool = True) -> dict:
        """آموزش چند مدل، مقایسه، انتخاب برتر بر اساس RMSE، ثبت در MLflow."""
        if len(series) < self.n_lags + self.horizon + 30:
            return {"status": "insufficient_data", "n_samples": len(series)}

        X, y = build_lag_dataset(series, n_lags=self.n_lags, horizon=self.horizon)
        if len(X) < 20:
            return {"status": "insufficient_windows", "n_windows": len(X)}

        X_train, X_test, y_train, y_test = temporal_train_test_split(X, y, self.test_ratio)
        candidates: list[ModelCandidate] = []

        # --- XGBoost ---
        xgb = XGBoostTemperaturePredictor(n_lags=self.n_lags)
        xgb.fit(X_train, y_train)
        xgb_metrics = evaluate(y_test, xgb.predict(X_test))
        xgb_run = self._log_candidate("xgboost", xgb, xgb_metrics, len(X_train), len(X_test))
        candidates.append(ModelCandidate("xgboost", xgb, xgb_metrics, xgb_run))

        # --- MLP (جایگزین عصبی سبک) ---
        mlp = MLPTemperaturePredictor(n_lags=self.n_lags)
        mlp.fit(X_train, y_train)
        mlp_metrics = evaluate(y_test, mlp.predict(X_test))
        mlp_run = self._log_candidate("mlp", mlp, mlp_metrics, len(X_train), len(X_test), sklearn_model=mlp._model)
        candidates.append(ModelCandidate("mlp", mlp, mlp_metrics, mlp_run))

        # --- LSTM (اختیاری) ---
        lstm = _try_build_lstm(self.n_lags)
        if lstm is not None:
            lstm.fit(X_train, y_train)
            lstm_metrics = evaluate(y_test, lstm.predict(X_test))
            lstm_run = self._log_candidate("lstm", lstm, lstm_metrics, len(X_train), len(X_test))
            candidates.append(ModelCandidate("lstm", lstm, lstm_metrics, lstm_run))

        # انتخاب برتر: کمترین RMSE
        best = min(candidates, key=lambda c: c.metrics["rmse"])
        self.active_model = best.predictor
        self.active_model_name = best.name
        self.active_metrics = best.metrics
        self.active_run_id = best.run_id
        self.drift.set_baseline(series)
        self.last_comparison = [
            {"name": c.name, "metrics": c.metrics, "run_id": c.run_id} for c in candidates
        ]

        version = None
        if promote_to_production and best.run_id:
            try:
                artifact = "model"
                version = self.mlflow.promote_best_to_production(best.run_id, artifact_path=artifact)
                self.active_version = version
            except Exception:  # noqa: BLE001
                logger.exception("ارتقا به Production ناموفق بود.")

        logger.info(
            "مدل برتر: %s (RMSE=%.4f, MAE=%.4f) از بین %d کاندیدا",
            best.name,
            best.metrics["rmse"],
            best.metrics["mae"],
            len(candidates),
        )
        return {
            "status": "ok",
            "best_model": best.name,
            "metrics": best.metrics,
            "run_id": best.run_id,
            "version": version,
            "comparison": self.last_comparison,
            "train_samples": len(X_train),
            "test_samples": len(X_test),
        }

    def _log_candidate(
        self,
        name: str,
        predictor: BaseTemperaturePredictor,
        metrics: dict[str, float],
        n_train: int,
        n_test: int,
        sklearn_model: Any | None = None,
    ) -> str | None:
        params = {
            "model_type": name,
            "n_lags": self.n_lags,
            "horizon_seconds": self.horizon,
            "train_samples": n_train,
            "test_samples": n_test,
        }
        try:
            artifact = sklearn_model if sklearn_model is not None else predictor
            return self.mlflow.log_training_run(
                model_name=name,
                params=params,
                metrics=metrics,
                model_artifact=artifact,
                tags={"phase": "3", "task": "reactor_temp_forecast"},
            )
        except Exception:  # noqa: BLE001
            logger.debug("ثبت MLflow برای %s ناموفق بود.", name)
            return None

    def predict(self, history: list[float]) -> float | None:
        if self.active_model is None:
            return None
        try:
            return float(self.active_model.predict_from_history(history))
        except Exception:  # noqa: BLE001
            logger.debug("پیش‌بینی مدل فعال ناموفق بود.")
            return None

    def check_drift_and_maybe_retrain(self, series: list[float]) -> dict:
        """اگر drift تشخیص داده شود، pipeline آموزش را دوباره اجرا می‌کند."""
        drift_result = self.drift.check(series)
        if not drift_result["drift_detected"]:
            return {"retrained": False, **drift_result}
        train_result = self.train_and_select(series, promote_to_production=True)
        return {"retrained": train_result.get("status") == "ok", "drift": drift_result, "train": train_result}
