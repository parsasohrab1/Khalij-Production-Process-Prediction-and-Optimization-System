"""سرویس پیش‌پردازش (Preprocessing) - FR-PRE-01, FR-PRE-02, FR-PRE-03.

مصرف داده خام از Kafka، حذف پرت، درون‌یابی مقادیر گم‌شده، نرمال‌سازی و
انتشار مجدد برای سرویس پیش‌بینی، همراه با کش آخرین مقدار در Redis برای سرو سریع.
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

from shared.logging_config import configure_logging
from shared.settings import get_settings

from .interpolation import interpolate_last_value, is_missing
from .normalization import SENSOR_RANGES, normalize_reading
from .outlier_detection import correct_outlier, is_outlier_zscore

settings = get_settings()
configure_logging("preprocessing", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Preprocessing Service", version="1.0.0")

_HISTORY_WINDOW = 60  # آخرین ۶۰ رکورد برای هر فیلد به‌عنوان تاریخچه محلی
_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=_HISTORY_WINDOW))
_stats = {"processed": 0, "outliers_corrected": 0, "interpolated": 0}


def _process_reading(raw: dict) -> dict:
    processed = dict(raw)
    processed["is_outlier_corrected"] = False
    processed["is_interpolated"] = False

    for field in SENSOR_RANGES:
        value = raw.get(field)
        history_key = field
        history = list(_history[history_key])

        if is_missing(value):
            value = interpolate_last_value(history, fallback=history[-1] if history else 0.0)
            processed["is_interpolated"] = True
            _stats["interpolated"] += 1
        elif is_outlier_zscore(value, history):
            value = correct_outlier(value, history)
            processed["is_outlier_corrected"] = True
            _stats["outliers_corrected"] += 1

        _history[history_key].append(value)
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

    def _run(self) -> None:
        logger.info("مصرف‌کننده پیش‌پردازش شروع به کار کرد.")
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
                raw = json.loads(msg.value().decode("utf-8"))
                processed = _process_reading(raw)
                self._publish(processed)
                self._store(processed)
                _stats["processed"] += 1
            except Exception:  # noqa: BLE001
                logger.exception("پردازش رکورد ناموفق بود.")

    def _publish(self, processed: dict) -> None:
        payload = json.dumps(processed, default=str).encode("utf-8")
        self._producer.produce(settings.kafka_topic_processed_sensors, value=payload)
        self._producer.poll(0)

    def _store(self, processed: dict) -> None:
        try:
            point = Point("processed_sensor_data").tag("unit_id", str(processed.get("unit_id", 1)))
            ts = processed.get("timestamp")
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts)
            point = point.time(ts or datetime.now(timezone.utc), WritePrecision.S)
            for field in SENSOR_RANGES:
                if field in processed:
                    point = point.field(field, float(processed[field]))
            self._write_api.write(bucket=settings.influxdb_bucket, org=settings.influxdb_org, record=point)
        except Exception:  # noqa: BLE001
            logger.debug("نوشتن داده پردازش‌شده در InfluxDB ناموفق بود.")

        try:
            self._redis.set(
                f"latest_reading:{processed.get('unit_id', 1)}", json.dumps(processed, default=str), ex=300
            )
        except Exception:  # noqa: BLE001
            logger.debug("به‌روزرسانی کش Redis ناموفق بود.")


_worker: PreprocessingWorker | None = None


@app.on_event("startup")
async def startup_event() -> None:
    global _worker
    _worker = PreprocessingWorker()
    _worker.start()
    logger.info("سرویس Preprocessing راه‌اندازی شد.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _worker:
        _worker.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", **_stats}
