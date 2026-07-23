"""سرویس جمع‌آوری داده (Data Ingestion) - R-GEN-01, FR-DATA-01..03.

وظیفه: دریافت داده از OPC-UA/Modbus (یا شبیه‌ساز در محیط توسعه)، ارسال به Kafka
برای مصرف توسط سرویس پیش‌پردازش، و ذخیره خام در InfluxDB برای بازه ۵ ساله.
"""
from __future__ import annotations

import asyncio
import logging
import os

from fastapi import FastAPI

from shared.logging_config import configure_logging
from shared.settings import get_settings

from .influx_writer import InfluxRawWriter
from .local_buffer import LocalBuffer
from .simulator import SensorSimulator

settings = get_settings()
configure_logging("data-ingestion", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Data Ingestion Service", version="1.0.0")

_state = {
    "running": False,
    "records_sent": 0,
    "records_buffered": 0,
    "source_mode": os.getenv("DATA_SOURCE_MODE", "simulator"),  # simulator | opcua | modbus
}


def _get_producer():
    from confluent_kafka import Producer  # local import: تنها زمانی که واقعاً لازم است

    return Producer({"bootstrap.servers": settings.kafka_bootstrap_servers, "client.id": "data-ingestion"})


@app.on_event("startup")
async def startup_event() -> None:
    app.state.buffer = LocalBuffer()
    try:
        app.state.influx_writer = InfluxRawWriter(
            url=settings.influxdb_url,
            token=settings.influxdb_token,
            org=settings.influxdb_org,
            bucket=settings.influxdb_bucket,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("اتصال اولیه به InfluxDB ناموفق بود، بعداً دوباره تلاش می‌شود: %s", exc)
        app.state.influx_writer = None

    app.state.producer = _get_producer()
    app.state.simulator = SensorSimulator()
    app.state.ingestion_task = asyncio.create_task(_ingestion_loop())
    logger.info("سرویس Data Ingestion راه‌اندازی شد (mode=%s).", _state["source_mode"])


@app.on_event("shutdown")
async def shutdown_event() -> None:
    _state["running"] = False
    task = getattr(app.state, "ingestion_task", None)
    if task:
        task.cancel()
    if getattr(app.state, "influx_writer", None):
        app.state.influx_writer.close()


async def _ingestion_loop() -> None:
    """حلقه اصلی: هر ثانیه یک رکورد از منبع داده می‌خواند و توزیع می‌کند (R-GEN-01)."""
    _state["running"] = True
    while _state["running"]:
        try:
            reading = app.state.simulator.next_reading()
            _dispatch_reading(reading)
        except Exception as exc:  # noqa: BLE001
            logger.exception("خطا در حلقه جمع‌آوری داده: %s", exc)
        await asyncio.sleep(1.0)


def _dispatch_reading(reading: dict) -> None:
    import json

    payload = {**reading, "timestamp": reading["timestamp"].isoformat()}

    try:
        app.state.producer.produce(
            settings.kafka_topic_raw_sensors,
            value=json.dumps(payload).encode("utf-8"),
        )
        app.state.producer.poll(0)
        _state["records_sent"] += 1
    except BufferError:
        app.state.buffer.push(settings.kafka_topic_raw_sensors, payload)
        _state["records_buffered"] += 1

    if app.state.influx_writer is not None:
        try:
            app.state.influx_writer.write_reading(reading)
        except Exception:  # noqa: BLE001
            logger.debug("نوشتن در InfluxDB ناموفق بود؛ رکورد رد شد (تلاش بعدی ادامه دارد).")

    _flush_local_buffer()


def _flush_local_buffer() -> None:
    """ارسال مجدد پیام‌های بافرشده پس از برقراری دوباره ارتباط (FR-DATA-03)."""
    for row_id, topic, payload in app.state.buffer.drain():
        try:
            import json

            app.state.producer.produce(topic, value=json.dumps(payload).encode("utf-8"))
            app.state.producer.poll(0)
            app.state.buffer.remove(row_id)
        except BufferError:
            break


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "mode": _state["source_mode"],
        "records_sent": _state["records_sent"],
        "records_buffered_pending": app.state.buffer.pending_count() if hasattr(app.state, "buffer") else 0,
    }


@app.get("/metrics")
async def metrics() -> dict:
    return _state
