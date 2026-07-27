"""سرویس پیش‌بینی و بهینه‌سازی (Prediction & Optimization) - FR-ML-01..03 + فاز ۳ MLOps.

مصرف داده پردازش‌شده از Kafka، پیش‌بینی دمای راکتور طی افق ۶۰ ثانیه با مدل‌های
آموزش‌دیده (XGBoost/MLP/LSTM)، مقایسه سیستماتیک، ثبت در MLflow Model Registry،
تشخیص Drift و Re-training خودکار.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import numpy as np
import redis
from confluent_kafka import Consumer, KafkaError, Producer
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.dlq import DeadLetterPublisher
from shared.health import install_health_probes
from shared.kafka_utils import high_throughput_consumer_config, high_throughput_producer_config
from shared.logging_config import configure_logging
from shared.metrics import inc_counter, install_prometheus_metrics, observe_seconds
from shared.scaling import LatencyTracker
from shared.schema_registry import SchemaName, try_validate
from shared.security import install_internal_api_key_middleware
from shared.settings import get_settings
from shared.tracing import setup_tracing

from .feedback import OptimizationFeedbackStore
from .optimizer import EvolutionaryRecommender, MultiVariableEvolutionaryOptimizer, estimate_efficiency
from .training_pipeline import TrainingPipeline
from .whatif import simulate_whatif

settings = get_settings()
configure_logging("prediction", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Prediction & Optimization Service", version="8.0.0")
install_internal_api_key_middleware(app)
install_prometheus_metrics(app, service_name="prediction")
setup_tracing("prediction", app)

_PREDICTION_BUDGET_MS = float(os.getenv("PREDICTION_LATENCY_BUDGET_MS", "2000"))
_latency = LatencyTracker(budget_ms=_PREDICTION_BUDGET_MS)

_HISTORY_WINDOW = 2000  # تاریخچه بزرگ‌تر برای آموزش batch و drift
_N_LAGS = 10
_HORIZON = 60
_RETRAIN_EVERY_N_RECORDS = int(os.getenv("RETRAIN_EVERY_N_RECORDS", "300"))
_DRIFT_CHECK_EVERY_N = int(os.getenv("DRIFT_CHECK_EVERY_N", "100"))
_PSI_THRESHOLD = float(os.getenv("DRIFT_PSI_THRESHOLD", "0.25"))
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
    "records_since_drift_check": 0,
    "latest_prediction": None,
    "latest_recommendation": None,
    "schema_rejected": 0,
    "dlq_published": 0,
    "drift_events": 0,
    "retrains": 0,
    "active_model": "linear_trend_fallback",
    "active_metrics": {},
    "active_version": None,
    "last_comparison": [],
    "latest_recommendation_id": None,
    "optimizations_generated": 0,
}

_pipeline = TrainingPipeline(
    mlflow_tracking_uri=settings.mlflow_tracking_uri,
    n_lags=_N_LAGS,
    horizon=_HORIZON,
    psi_threshold=_PSI_THRESHOLD,
)
_recommender = EvolutionaryRecommender()  # نگه‌داری برای سازگاری API قدیمی / تست
_mv_optimizer = MultiVariableEvolutionaryOptimizer()
_feedback_store = OptimizationFeedbackStore(settings.postgres_dsn)


def _linear_trend_forecast(history: list[float], horizon: int) -> float:
    n = min(len(history), 30)
    if n < 2:
        return history[-1] if history else 0.0
    y = np.asarray(history[-n:], dtype=float)
    x = np.arange(n)
    slope, intercept = np.polyfit(x, y, 1)
    return float(slope * (n - 1 + horizon) + intercept)


def _run_training(unit_id: int, reason: str = "scheduled") -> dict:
    series = list(_history[unit_id]["reactor_temp_c"])
    result = _pipeline.train_and_select(series, promote_to_production=True)
    if result.get("status") == "ok":
        _stats["model_trained"] = True
        _stats["records_since_train"] = 0
        _stats["retrains"] += 1
        _stats["active_model"] = result["best_model"]
        _stats["active_metrics"] = result["metrics"]
        _stats["active_version"] = result.get("version")
        _stats["last_comparison"] = result.get("comparison", [])
        logger.info("آموزش کامل شد (reason=%s): %s", reason, result["best_model"])
    return result


def _predict_reactor_temp(unit_id: int) -> tuple[float, str]:
    with _latency.measure() as ctx:
        series = list(_history[unit_id]["reactor_temp_c"])
        pred = _pipeline.predict(series)
        if pred is not None:
            result = (pred, _pipeline.active_model_name)
        else:
            result = (_linear_trend_forecast(series, _HORIZON), "linear_trend_fallback")
    if getattr(ctx, "elapsed_ms", 0) > _PREDICTION_BUDGET_MS:
        logger.warning(
            "نقض بودجه تأخیر پیش‌بینی (NFR-PER-01): %.1fms > %.0fms unit=%s",
            ctx.elapsed_ms,
            _PREDICTION_BUDGET_MS,
            unit_id,
        )
    observe_seconds(
        "khalij_prediction_latency_seconds",
        getattr(ctx, "elapsed_ms", 0) / 1000.0,
        service="prediction",
    )
    inc_counter("khalij_predictions_total", service="prediction")
    return result


class PredictionWorker:
    def __init__(self) -> None:
        self._consumer = Consumer(
            high_throughput_consumer_config(
                settings.kafka_bootstrap_servers,
                f"{settings.kafka_consumer_group}-prediction",
            )
        )
        self._consumer.subscribe([settings.kafka_topic_processed_sensors])
        self._producer = Producer(
            high_throughput_producer_config(settings.kafka_bootstrap_servers, client_id="prediction")
        )
        self._dlq = DeadLetterPublisher(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            dlq_topic=settings.kafka_topic_processed_dlq,
            client_id="prediction-dlq",
        )
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
        self._dlq.flush()

    def _consume_loop(self) -> None:
        logger.info("مصرف‌کننده پیش‌بینی (فاز ۳: MLOps) شروع به کار کرد.")
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
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                _stats["schema_rejected"] += 1
                self._dlq.publish(
                    original_topic=settings.kafka_topic_processed_sensors,
                    payload=msg.value().decode("utf-8", errors="replace"),
                    error=str(exc),
                    schema_name=SchemaName.PROCESSED_SENSOR.value,
                    extra={"reason": "invalid_json"},
                )
                _stats["dlq_published"] += 1
                continue

            _, schema_err = try_validate(reading, SchemaName.PROCESSED_SENSOR)
            if schema_err is not None:
                _stats["schema_rejected"] += 1
                self._dlq.publish(
                    original_topic=settings.kafka_topic_processed_sensors,
                    payload=reading,
                    error=str(schema_err),
                    schema_name=SchemaName.PROCESSED_SENSOR.value,
                    extra={"reason": "schema_validation"},
                )
                _stats["dlq_published"] += 1
                continue

            try:
                self._handle_reading(reading)
            except Exception:  # noqa: BLE001
                logger.exception("پردازش رکورد پیش‌بینی ناموفق بود.")

    def _handle_reading(self, reading: dict) -> None:
        unit_id = int(reading.get("unit_id", 1))
        for field in ("reactor_temp_c", "reactor_pressure_bar", "feed_flow_m3h"):
            if field in reading:
                _history[unit_id][field].append(float(reading[field]))

        _stats["records_since_train"] += 1
        _stats["records_since_drift_check"] += 1

        # Re-training دوره‌ای
        if _stats["records_since_train"] >= _RETRAIN_EVERY_N_RECORDS:
            _run_training(unit_id, reason="scheduled")

        # Drift Detection دوره‌ای
        if _stats["records_since_drift_check"] >= _DRIFT_CHECK_EVERY_N and _pipeline.drift.has_baseline:
            _stats["records_since_drift_check"] = 0
            series = list(_history[unit_id]["reactor_temp_c"])
            drift_result = _pipeline.check_drift_and_maybe_retrain(series)
            if drift_result.get("drift", {}).get("drift_detected") or drift_result.get("retrained"):
                _stats["drift_events"] += 1
            if drift_result.get("retrained"):
                _stats["model_trained"] = True
                _stats["retrains"] += 1
                train = drift_result.get("train", {})
                _stats["active_model"] = train.get("best_model", _stats["active_model"])
                _stats["active_metrics"] = train.get("metrics", {})
                _stats["active_version"] = train.get("version")
                _stats["last_comparison"] = train.get("comparison", [])

        predicted_temp, model_name = _predict_reactor_temp(unit_id)
        nominal = settings.reactor_nominal_temp_c
        deviation_percent = abs(predicted_temp - nominal) / nominal * 100 if nominal else 0.0

        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "unit_id": unit_id,
            "horizon_seconds": _HORIZON,
            "predicted_reactor_temp_c": round(predicted_temp, 2),
            "nominal_reactor_temp_c": nominal,
            "deviation_percent": round(deviation_percent, 2),
            "model_name": model_name,
            "model_version": _stats.get("active_version"),
            "mlflow_run_id": _pipeline.active_run_id,
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
                temp = series["reactor_temp_c"][-1]
                pressure = series["reactor_pressure_bar"][-1] if series["reactor_pressure_bar"] else 25.0
                feed = series["feed_flow_m3h"][-1]
                # فاز ۴: بهینه‌سازی چندمتغیره با قیود ایمنی
                recommendation = _mv_optimizer.optimize(
                    reactor_temp_c=temp,
                    current_pressure_bar=pressure,
                    current_feed_flow=feed,
                )
                recommendation.update(
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "unit_id": unit_id,
                    }
                )
                _stats["latest_recommendation"] = recommendation
                _stats["optimizations_generated"] += 1
                self._publish(settings.kafka_topic_predictions, {"type": "recommendation", **recommendation})
                self._store_recommendation(unit_id, recommendation)
                try:
                    self._redis.set(
                        f"latest_recommendation:{unit_id}",
                        json.dumps(recommendation, default=str),
                        ex=600,
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("کش Redis توصیه ناموفق بود.")

    def _store_recommendation(self, unit_id: int, recommendation: dict) -> None:
        rec_id = _feedback_store.insert_recommendation(
            unit_id, recommendation, model_run_id=_pipeline.active_run_id
        )
        if rec_id is not None:
            recommendation["recommendation_id"] = rec_id
            _stats["latest_recommendation_id"] = rec_id
            _stats["latest_recommendation"] = recommendation
            try:
                self._redis.set(
                    f"latest_recommendation:{unit_id}",
                    json.dumps(recommendation, default=str),
                    ex=600,
                )
            except Exception:  # noqa: BLE001
                logger.debug("کش Redis توصیه ناموفق بود.")

    def _publish(self, topic: str, payload: dict) -> None:
        self._producer.produce(topic, value=json.dumps(payload, default=str).encode("utf-8"))
        self._producer.poll(0)


_worker: PredictionWorker | None = None


@app.on_event("startup")
async def startup_event() -> None:
    global _worker
    _feedback_store.ensure_schema()
    _worker = PredictionWorker()
    _worker.start()
    logger.info("سرویس Prediction (فاز ۷: مقیاس/کارایی) راه‌اندازی شد.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _worker:
        _worker.stop()


install_health_probes(
    app,
    service_name="prediction",
    ready_check=lambda: _worker is not None,
    details=lambda: {"latency": _latency.snapshot(), "predictions_made": _stats["predictions_made"]},
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "phase": 7, "latency": _latency.snapshot(), **_stats}


@app.get("/metrics/latency")
async def prediction_latency() -> dict:
    """متریک تأخیر پیش‌بینی نسبت به بودجه NFR-PER-01 (<۲ثانیه)."""
    snap = _latency.snapshot()
    snap["nfr_per_01_budget_ms"] = _PREDICTION_BUDGET_MS
    snap["nfr_per_01_ok"] = (snap.get("p95_ms") or 0) <= _PREDICTION_BUDGET_MS
    return snap


@app.get("/predict/latest")
async def latest_prediction() -> dict:
    return _stats["latest_prediction"] or {}


@app.get("/recommend/latest")
async def latest_recommendation() -> dict:
    return _stats["latest_recommendation"] or {}


@app.post("/train")
async def trigger_training(unit_id: int = 1) -> dict:
    """آموزش batch دستی با مقایسه مدل‌ها و ارتقا به Production."""
    return _run_training(unit_id, reason="manual_api")


@app.get("/models/comparison")
async def model_comparison() -> dict:
    """نتیجه آخرین مقایسه XGBoost / MLP / LSTM."""
    return {
        "active_model": _stats["active_model"],
        "active_metrics": _stats["active_metrics"],
        "active_version": _stats["active_version"],
        "comparison": _stats["last_comparison"],
    }


@app.get("/models/production")
async def production_model() -> dict:
    info = _pipeline.mlflow.get_production_model_info()
    return info or {"status": "no_production_model"}


@app.post("/drift/check")
async def drift_check(unit_id: int = 1) -> dict:
    series = list(_history[unit_id]["reactor_temp_c"])
    return _pipeline.check_drift_and_maybe_retrain(series)


@app.get("/optimize/preview")
async def preview_efficiency(reactor_temp_c: float, pressure_bar: float, feed_flow_m3h: float) -> dict:
    return {"estimated_efficiency": estimate_efficiency(reactor_temp_c, pressure_bar, feed_flow_m3h)}


# ---------------------------------------------------------------------
# فاز ۴: بهینه‌سازی چندمتغیره، What-if، حلقه بسته
# ---------------------------------------------------------------------
class OptimizeRequest(BaseModel):
    reactor_temp_c: float
    pressure_bar: float
    feed_flow_m3h: float
    unit_id: int = 1
    persist: bool = True


class WhatIfRequest(BaseModel):
    reactor_temp_c: float
    current_pressure_bar: float
    current_feed_flow: float
    proposed_pressure_bar: float
    proposed_feed_flow: float


class ApplyRecommendationRequest(BaseModel):
    recommendation_id: int
    operator_id: int = 1
    run_whatif_first: bool = True


class FeedbackRequest(BaseModel):
    recommendation_id: int
    actual_efficiency: float = Field(..., ge=0, le=100)
    operator_id: int | None = None


@app.post("/optimize")
async def optimize_setpoints(body: OptimizeRequest) -> dict:
    """بهینه‌سازی چندمتغیره دبی+فشار با قیود ایمنی سخت."""
    result = _mv_optimizer.optimize(
        reactor_temp_c=body.reactor_temp_c,
        current_pressure_bar=body.pressure_bar,
        current_feed_flow=body.feed_flow_m3h,
    )
    result.update({"timestamp": datetime.now(timezone.utc).isoformat(), "unit_id": body.unit_id})
    if body.persist:
        rec_id = _feedback_store.insert_recommendation(
            body.unit_id, result, model_run_id=_pipeline.active_run_id
        )
        result["recommendation_id"] = rec_id
        _stats["latest_recommendation"] = result
        _stats["latest_recommendation_id"] = rec_id
        _stats["optimizations_generated"] += 1
        if _worker is not None:
            try:
                _worker._redis.set(
                    f"latest_recommendation:{body.unit_id}",
                    json.dumps(result, default=str),
                    ex=600,
                )
            except Exception:  # noqa: BLE001
                logger.debug("کش Redis توصیه (API optimize) ناموفق بود.")
    return result


@app.post("/optimize/whatif")
async def optimize_whatif(body: WhatIfRequest) -> dict:
    """شبیه‌سازی What-if پیش از اعمال توصیه توسط اپراتور."""
    return simulate_whatif(
        reactor_temp_c=body.reactor_temp_c,
        current_pressure_bar=body.current_pressure_bar,
        current_feed_flow=body.current_feed_flow,
        proposed_pressure_bar=body.proposed_pressure_bar,
        proposed_feed_flow=body.proposed_feed_flow,
    )


@app.post("/optimize/apply")
async def apply_recommendation(body: ApplyRecommendationRequest) -> dict:
    """اعمال توصیه پس از تأیید اپراتور (و در صورت نیاز What-if)."""
    whatif_snapshot = None
    latest = _stats.get("latest_recommendation") or {}
    if body.run_whatif_first and latest.get("recommended") and latest.get("current"):
        whatif_snapshot = simulate_whatif(
            reactor_temp_c=float(latest.get("reactor_temp_c", settings.reactor_nominal_temp_c)),
            current_pressure_bar=float(latest["current"]["pressure_bar"]),
            current_feed_flow=float(latest["current"]["feed_flow_m3h"]),
            proposed_pressure_bar=float(latest["recommended"]["pressure_bar"]),
            proposed_feed_flow=float(latest["recommended"]["feed_flow_m3h"]),
        )
        if not whatif_snapshot["constraints_satisfied"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "توصیه قیود ایمنی را نقض می‌کند و قابل اعمال نیست.",
                    "whatif": whatif_snapshot,
                },
            )
    ok = _feedback_store.apply_recommendation(
        body.recommendation_id, body.operator_id, whatif_snapshot=whatif_snapshot
    )
    if not ok:
        raise HTTPException(status_code=404, detail="توصیه یافت نشد یا قبلاً اعمال شده است.")
    return {"applied": True, "recommendation_id": body.recommendation_id, "whatif": whatif_snapshot}


@app.post("/optimize/feedback")
async def record_optimization_feedback(body: FeedbackRequest) -> dict:
    """ثبت راندمان واقعی پس از اعمال توصیه (حلقه بسته)."""
    result = _feedback_store.record_feedback(
        body.recommendation_id, body.actual_efficiency, operator_id=body.operator_id
    )
    if result is None:
        raise HTTPException(status_code=404, detail="توصیه اعمال‌شده برای بازخورد یافت نشد.")
    return result


@app.get("/optimize/feedback/summary")
async def optimization_feedback_summary(limit: int = 50) -> dict:
    return _feedback_store.feedback_summary(limit=limit)
