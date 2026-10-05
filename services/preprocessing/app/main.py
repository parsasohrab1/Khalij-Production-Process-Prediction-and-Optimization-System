"""Preprocessing service (Preprocessing) - FR-PRE-01..03 + phase 2 (Schema/DLQ/Quality).

Consumes raw data from Kafka, validates the schema, checks quality, removes outliers, interpolates,
normalizes and republishes. Invalid messages are sent to the Dead Letter Queue.
"""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone

import redis
from confluent_kafka import Consumer, KafkaError, Producer
from fastapi import FastAPI
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from shared.data_quality import validate_record
from shared.dlq import DeadLetterPublisher
from shared.health import install_health_probes
from shared.logging_config import configure_logging
from shared.metrics import install_prometheus_metrics
from shared.schema_registry import SchemaName, stamp_schema_metadata, try_validate
from shared.security import install_internal_api_key_middleware
from shared.settings import get_settings
from shared.tracing import setup_tracing

from .interpolation import interpolate_last_value, is_missing
from .normalization import SENSOR_RANGES, normalize_reading
from .outlier_detection import correct_outlier, is_outlier_zscore

settings = get_settings()
configure_logging("preprocessing", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Preprocessing Service", version="8.0.0")
install_internal_api_key_middleware(app)
install_prometheus_metrics(app, service_name="preprocessing")
setup_tracing("preprocessing", app)
install_health_probes(app, service_name="preprocessing", ready_check=lambda: True)

_HISTORY_WINDOW = 60
_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=_HISTORY_WINDOW))
_stats = {
    "processed": 0,
    "outliers_corrected": 0,
    "interpolated": 0,
    "schema_rejected": 0,
    "quality_rejected": 0,
    "dlq_published": 0,
    "quality_warnings": 0,
}


def _process_reading(raw: dict) -> dict:
    processed = dict(raw)
    processed["is_outlier_corrected"] = False
    processed["is_interpolated"] = False

    for field in SENSOR_RANGES:
        value = raw.get(field)
        history = list(_history[field])

        if is_missing(value):
            value = interpolate_last_value(history, fallback=history[-1] if history else 0.0)
            processed["is_interpolated"] = True
            _stats["interpolated"] += 1
        elif is_outlier_zscore(value, history):
            value = correct_outlier(value, history)
            processed["is_outlier_corrected"] = True
            _stats["outliers_corrected"] += 1

        _history[field].append(value)
        processed[field] = value

    processed["normalized"] = normalize_reading(processed)
    return processed


class PreprocessingWorker:
    def __init__(self) -> None:
        self._consumer = Consumer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "group.id": f"{settings.kafka_consumer_group}-preprocessing",
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
            }
        )
        self._consumer.subscribe([settings.kafka_topic_raw_sensors])
        self._producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
        self._dlq = DeadLetterPublisher(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            dlq_topic=settings.kafka_topic_raw_dlq,
            client_id="preprocessing-dlq",
        )
        self._influx = InfluxDBClient(
            url=settings.influxdb_url, token=settings.influxdb_token, org=settings.influxdb_org
        )
        self._write_api = self._influx.write_api(write_options=SYNCHRONOUS)
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._consumer.close()
        self._dlq.flush()

    def _send_dlq(self, raw: dict | str, error: str, reason: str) -> None:
        self._dlq.publish(
            original_topic=settings.kafka_topic_raw_sensors,
            payload=raw,
            error=error,
            schema_name=SchemaName.RAW_SENSOR.value,
            extra={"reason": reason},
        )
        _stats["dlq_published"] += 1

    def _run(self) -> None:
        logger.info("Preprocessing consumer (phase 2: Schema+DLQ+Quality) started.")
        while not self._stop.is_set():
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("Kafka error: %s", msg.error())
                continue

            raw_bytes = msg.value()
            try:
                raw = json.loads(raw_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                _stats["schema_rejected"] += 1
                self._send_dlq(raw_bytes.decode("utf-8", errors="replace"), str(exc), "invalid_json")
                continue

            # 1) Schema Registry validation
            _, schema_err = try_validate(raw, SchemaName.RAW_SENSOR)
            if schema_err is not None:
                _stats["schema_rejected"] += 1
                self._send_dlq(raw, str(schema_err), "schema_validation")
                continue

            # 2) Data quality: mandatory fields; range warning (without rejecting — FR-PRE-01 corrects outliers)
            quality = validate_record(raw, check_freshness=False)
            required_failed = any(r.name == "expect_required_fields" and not r.success for r in quality.results)
            if required_failed:
                _stats["quality_rejected"] += 1
                self._send_dlq(raw, "missing required fields", "quality_required_fields")
                continue
            if not quality.passed:
                _stats["quality_warnings"] += 1
                logger.debug("Data quality warning: %s", [f.detail for f in quality.failures])

            try:
                processed = _process_reading(raw)
                self._publish(processed)
                self._store(processed)
                _stats["processed"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("Record processing failed.")
                self._send_dlq(raw, str(exc), "processing_exception")

    def _publish(self, processed: dict) -> None:
        stamped = stamp_schema_metadata(processed, SchemaName.PROCESSED_SENSOR)
        payload = json.dumps(stamped, default=str).encode("utf-8")
        self._producer.produce(settings.kafka_topic_processed_sensors, value=payload)
        self._producer.poll(0)

    def _store(self, processed: dict) -> None:
        try:
            point = Point("processed_sensor_data").tag("unit_id", str(processed.get("unit_id", 1)))
            ts = processed.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            point = point.time(ts or datetime.now(timezone.utc), WritePrecision.S)
            for field in SENSOR_RANGES:
                if field in processed:
                    point = point.field(field, float(processed[field]))
            self._write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)
        except Exception:  # noqa: BLE001
            logger.debug("Writing processed data to InfluxDB failed.")

        try:
            self._redis.set(
                f"latest_reading:{processed.get('unit_id', 1)}", json.dumps(processed, default=str), ex=300
            )
        except Exception:  # noqa: BLE001
            logger.debug("Updating the Redis cache failed.")


_worker: PreprocessingWorker | None = None


@app.on_event("startup")
async def startup_event() -> None:
    global _worker
    _worker = PreprocessingWorker()
    _worker.start()
    logger.info("Preprocessing service started.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _worker:
        _worker.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", **_stats}


@app.get("/quality/stats")
async def quality_stats() -> dict:
    """Data quality and DLQ statistics for phase 2 monitoring."""
    return {
        "processed": _stats["processed"],
        "schema_rejected": _stats["schema_rejected"],
        "quality_rejected": _stats["quality_rejected"],
        "quality_warnings": _stats["quality_warnings"],
        "dlq_published": _stats["dlq_published"],
        "reject_rate": (
            (_stats["schema_rejected"] + _stats["quality_rejected"])
            / max(1, _stats["processed"] + _stats["schema_rejected"] + _stats["quality_rejected"])
        ),
    }
