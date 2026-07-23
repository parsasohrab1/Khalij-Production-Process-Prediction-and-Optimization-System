"""سرویس پیش‌بینی و بهینه‌سازی (Prediction & Optimization) - FR-ML-01..03.

مصرف داده پردازش‌شده از Kafka، پیش‌بینی دمای راکتور طی افق ۶۰ ثانیه، صدور
هشدار بحرانی در صورت انحراف بیش از حد آستانه، و توصیه دبی خوراک بهینه با
الگوریتم تکاملی. مدل‌ها در MLflow ثبت و نسخه‌بندی می‌شوند.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import mlflow
import numpy as np
import psycopg2
import redis
from confluent_kafka import Consumer, KafkaError, Producer
from fastapi import FastAPI

from shared.logging_config import configure_logging
from shared.settings import get_settings

from .models.xgboost_model import XGBoostTemperaturePredictor
from .optimizer import EvolutionaryRecommender, estimate_efficiency

settings = get_settings()
configure_logging("prediction", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Prediction & Optimization Service", version="1.0.0")

_HISTORY_WINDOW = 600  # ۱۰ دقیقه تاریخچه با نرخ ۱ رکورد در ثانیه
_N_LAGS = 10
_HORIZON = 60
_RETRAIN_EVERY_N_RECORDS = 200
_RECOMMEND_INTERVAL_S = 30

_history: dict[int, dict[str, deque]] = defaultdict(
    lambda: {
        "reactor_temp_c": deque(maxlen=_HISTORY_WINDOW),
        "reactor_pressure_bar": deque(maxlen=_HISTORY_WINDOW),
        "feed_flow_m3h": deque(maxlen=_HISTORY_WINDOW),
    }
)
_stats = {
    "predictions_made": 0,
    "critical_alerts_raised": 0,
    "model_trained": False,
    "records_since_train": 0,
    "latest_prediction": None,
    "latest_recommendation": None,
}

_model = XGBoostTemperaturePredictor(n_lags=_N_LAGS)
_recommender = EvolutionaryRecommender()


def _linear_trend_forecast(history: list[float], horizon: int) -> float:
    """پیش‌بینی سریع مبتنی بر برون‌یابی خطی، تا زمانی که مدل XGBoost آموزش کافی نبیند."""
    n = min(len(history), 30)
    if n < 2:
        return history[-1] if history else 0.0
    y = np.asarray(history[-n:], dtype=float)
    x = np.arange(n)
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope * (n - 1 + horizon) + intercept)


def _maybe_train_model(unit_id: int) -> None:
    series = list(_history[unit_id]["reactor_temp_c"])
    if len(series) < _N_LAGS + _HORIZON + 20:
        return
    X, y = XGBoostTemperaturePredictor.build_training_set(series, n_lags=_N_LAGS, horizon=_HORIZON)
    if len(X) < 10:
        return
    _model.fit(X, y)
    _stats["model_trained"] = True
    _stats["records_since_train"] = 0
    logger.info("مدل XGBoost با %d نمونه آموزش دید.", len(X))
    try:
        mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
        with mlflow.start_run(run_name=f"xgboost_reactor_temp_unit_{unit_id}"):
            mlflow.log_param("n_lags", _N_LAGS)
            mlflow.log_param("horizon_seconds", _HORIZON)
            mlflow.log_metric("training_samples", len(X))
    except Exception:  # noqa: BLE001
        logger.debug("ثبت اجرا در MLflow ناموفق بود (سرویس MLflow در دسترس نیست).")


def _predict_reactor_temp(unit_id: int) -> float:
    series = list(_history[unit_id]["reactor_temp_c"])
    if _stats["model_trained"] and len(series) >= _N_LAGS:
        try:
            return _model.predict_from_history(series)
        except Exception:  # noqa: BLE001
            logger.debug("پیش‌بینی XGBoost ناموفق بود، بازگشت به برون‌یابی خطی.")
    return _linear_trend_forecast(series, _HORIZON)


class PredictionWorker:
    def __init__(self) -> None:
        self._consumer = Consumer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "group.id": f"{settings.kafka_consumer_group}-prediction",
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
            }
        )
        self._consumer.subscribe([settings.kafka_topic_processed_sensors])
        self._producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._stop = threading.Event()
        self._consume_thread = threading.Thread(target=self._consume_loop, daemon=True)
        self._recommend_thread = threading.Thread(target=self._recommend_loop, daemon=True)

    def start(self) -> None:
        self._consume_thread.start()
        self._recommend_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._consumer.close()

    def _consume_loop(self) -> None:
        logger.info("مصرف‌کننده پیش‌بینی شروع به کار کرد.")
        while not self._stop.is_set():
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("خطای Kafka: %s", msg.error())
                continue
            try:
                reading = json.loads(msg.value().decode("utf-8"))
                self._handle_reading(reading)
            except Exception:  # noqa: BLE001
                logger.exception("پردازش رکورد پیش‌بینی ناموفق بود.")

    def _handle_reading(self, reading: dict) -> None:
        unit_id = int(reading.get("unit_id", 1))
        for field in ("reactor_temp_c", "reactor_pressure_bar", "feed_flow_m3h"):
            if field in reading:
                _history[unit_id][field].append(float(reading[field]))

        _stats["records_since_train"] += 1
        if _stats["records_since_train"] >= _RETRAIN_EVERY_N_RECORDS:
            _maybe_train_model(unit_id)

        predicted_temp = _predict_reactor_temp(unit_id)
        nominal = settings.reactor_nominal_temp_c
        deviation_percent = abs(predicted_temp - nominal) / nominal * 100 if nominal else 0.0

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "unit_id": unit_id,
            "horizon_seconds": _HORIZON,
            "predicted_reactor_temp_c": round(predicted_temp, 2),
            "nominal_reactor_temp_c": nominal,
            "deviation_percent": round(deviation_percent, 2),
            "model_name": _model.name if _stats["model_trained"] else "linear_trend_fallback",
        }
        _stats["predictions_made"] += 1
        _stats["latest_prediction"] = result
        self._publish(settings.kafka_topic_predictions, result)
        self._redis.set(f"latest_prediction:{unit_id}", json.dumps(result), ex=300)

        if deviation_percent > settings.critical_deviation_percent:
            self._raise_critical_alert(unit_id, result)

    def _raise_critical_alert(self, unit_id: int, prediction: dict) -> None:
        alert = {
            "level": "critical",
            "message": (
                f"پیش‌بینی انحراف {prediction['deviation_percent']}٪ از دمای نامی راکتور "
                f"(واحد {unit_id}) طی {_HORIZON} ثانیه آینده - FR-ML-02"
            ),
            "sensor_tag": "reactor_temp_c",
            "predicted_value": prediction["predicted_reactor_temp_c"],
            "nominal_value": prediction["nominal_reactor_temp_c"],
            "deviation_percent": prediction["deviation_percent"],
            "raised_at": datetime.now(timezone.utc).isoformat(),
        }
        _stats["critical_alerts_raised"] += 1
        self._publish(settings.kafka_topic_alerts, alert)
        logger.warning("هشدار بحرانی صادر شد: %s", alert["message"])

    def _recommend_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(_RECOMMEND_INTERVAL_S)
            for unit_id, series in list(_history.items()):
                if not series["reactor_temp_c"] or not series["feed_flow_m3h"]:
                    continue
                recommendation = _recommender.recommend(
                    reactor_temp_c=series["reactor_temp_c"][-1],
                    pressure_bar=series["reactor_pressure_bar"][-1] if series["reactor_pressure_bar"] else 25.0,
                    current_feed_flow=series["feed_flow_m3h"][-1],
                )
                recommendation.update(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "unit_id": unit_id,
                        "variable_name": "feed_flow_m3h",
                    }
                )
                _stats["latest_recommendation"] = recommendation
                self._publish(settings.kafka_topic_predictions, {"type": "recommendation", **recommendation})
                self._store_recommendation(unit_id, recommendation)

    def _store_recommendation(self, unit_id: int, recommendation: dict) -> None:
        try:
            conn = psycopg2.connect(settings.postgres_dsn.replace("postgresql+psycopg2", "postgresql"))
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO optimization_recommendations
                        (unit_id, variable_name, current_value, recommended_value, expected_efficiency_gain)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        unit_id,
                        recommendation["variable_name"],
                        recommendation["current_value"],
                        recommendation["recommended_value"],
                        recommendation["expected_efficiency_gain"],
                    ),
                )
            conn.close()
        except Exception:  # noqa: BLE001
            logger.debug("ذخیره توصیه بهینه‌سازی در PostgreSQL ناموفق بود.")

    def _publish(self, topic: str, payload: dict) -> None:
        self._producer.produce(topic, value=json.dumps(payload, default=str).encode("utf-8"))
        self._producer.poll(0)


_worker: PredictionWorker | None = None


@app.on_event("startup")
async def startup_event() -> None:
    global _worker
    _worker = PredictionWorker()
    _worker.start()
    logger.info("سرویس Prediction & Optimization راه‌اندازی شد.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _worker:
        _worker.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", **_stats}


@app.get("/predict/latest")
async def latest_prediction() -> dict:
    return _stats["latest_prediction"] or {}


@app.get("/recommend/latest")
async def latest_recommendation() -> dict:
    return _stats["latest_recommendation"] or {}


@app.post("/train")
async def trigger_training(unit_id: int = 1) -> dict:
    _maybe_train_model(unit_id)
    return {"model_trained": _stats["model_trained"]}


@app.get("/optimize/preview")
async def preview_efficiency(reactor_temp_c: float, pressure_bar: float, feed_flow_m3h: float) -> dict:
    return {"estimated_efficiency": estimate_efficiency(reactor_temp_c, pressure_bar, feed_flow_m3h)}
