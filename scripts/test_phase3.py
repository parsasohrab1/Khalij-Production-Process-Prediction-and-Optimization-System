"""Phase 3 unit tests: metrics, drift, training pipeline (without needing a live MLflow).

Run:
    python scripts/test_phase3.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "prediction"))
sys.path.insert(0, str(ROOT))


def _synthetic_temp(n: int = 800, seed: int = 42) -> list[float]:
    rng = np.random.default_rng(seed)
    t = np.linspace(0, 20 * np.pi, n)
    series = 250 + 30 * np.sin(t * 0.5) + 0.01 * np.arange(n) + rng.normal(0, 2, n)
    return np.clip(series, 150, 350).tolist()


def test_metrics() -> None:
    from app.metrics import evaluate, mae, rmse

    y_true = np.array([1.0, 2.0, 3.0])
    y_pred = np.array([1.0, 2.5, 2.5])
    assert abs(mae(y_true, y_pred) - (0 + 0.5 + 0.5) / 3) < 1e-6
    assert rmse(y_true, y_pred) > 0
    m = evaluate(y_true, y_pred)
    assert "mae" in m and "rmse" in m and "mape" in m
    print("[OK] metrics")


def test_drift() -> None:
    from app.drift import DriftDetector, population_stability_index

    baseline = np.random.default_rng(0).normal(250, 10, 500)
    same = np.random.default_rng(1).normal(250, 10, 500)
    shifted = np.random.default_rng(2).normal(280, 10, 500)

    psi_same = population_stability_index(baseline, same)
    psi_shift = population_stability_index(baseline, shifted)
    assert psi_shift > psi_same

    det = DriftDetector(psi_threshold=0.1, min_samples=100)
    det.set_baseline(baseline.tolist())
    result = det.check(shifted.tolist())
    assert result["drift_detected"] is True
    print("[OK] drift detection")


def test_training_pipeline_without_mlflow() -> None:
    """XGBoost+MLP training on synthetic data; MLflow may be unavailable."""
    import os

    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "2"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"

    from app.metrics import evaluate
    from app.models.mlp_model import MLPTemperaturePredictor
    from app.models.xgboost_model import XGBoostTemperaturePredictor
    from app.training_pipeline import TrainingPipeline, build_lag_dataset, temporal_train_test_split

    series = _synthetic_temp(800)
    X, y = build_lag_dataset(series, n_lags=10, horizon=60)
    assert len(X) > 50
    X_train, X_test, y_train, y_test = temporal_train_test_split(X, y, 0.2)

    xgb = XGBoostTemperaturePredictor(n_lags=10, n_estimators=50)
    xgb.fit(X_train, y_train)
    xgb_m = evaluate(y_test, xgb.predict(X_test))

    mlp = MLPTemperaturePredictor(n_lags=10, max_iter=80, hidden_layer_sizes=(32,))
    mlp.fit(X_train, y_train)
    mlp_m = evaluate(y_test, mlp.predict(X_test))

    assert xgb_m["rmse"] < 50
    assert mlp_m["rmse"] < 80
    pred = xgb.predict_from_history(series[-10:])
    assert 150 <= pred <= 350

    # complete pipeline with a local file store
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    mlruns = ROOT / ".mlruns_test"
    mlruns.mkdir(exist_ok=True)
    pipeline = TrainingPipeline(
        mlflow_tracking_uri=str(mlruns),
        n_lags=10,
        horizon=60,
    )
    result = pipeline.train_and_select(series, promote_to_production=False)
    assert result["status"] == "ok"
    assert result["best_model"] in ("xgboost", "mlp", "lstm")
    assert "comparison" in result and len(result["comparison"]) >= 2
    print(f"[OK] training pipeline best={result['best_model']} rmse={result['metrics']['rmse']}")


if __name__ == "__main__":
    test_metrics()
    test_drift()
    test_training_pipeline_without_mlflow()
    print("\nAll Phase-3 tests passed.")
