"""سرویس جمع‌آوری داده (Data Ingestion) - R-GEN-01, FR-DATA-01..03 + فاز ۷ مقیاس.

سوییچ منبع: simulator | opcua | modbus
فاز ۷: شاردینگ واحدها، batch Kafka/Influx، بک‌پرشر، readiness.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from fastapi import FastAPI

from shared.health import install_health_probes
from shared.kafka_utils import high_throughput_producer_config
from shared.logging_config import configure_logging
from shared.metrics import inc_counter, install_prometheus_metrics
from shared.scaling import (
    BackpressureController,
    filter_units_for_shard,
    parse_unit_ids,
    partition_key_for_unit,
    resolve_shard_id,
)
from shared.schema_registry import SchemaName, stamp_schema_metadata
from shared.security import install_internal_api_key_middleware
from shared.settings import get_settings
from shared.tracing import setup_tracing

from .circuit_breaker import CircuitBreaker
from .influx_writer import InfluxRawWriter
from .local_buffer import LocalBuffer
from .protocols.modbus_client import ModbusClient
from .protocols.opcua_client import OpcUaClient
from .simulator import SensorSimulator
from .tag_mapping import UnitTagMapping, load_tag_mapping

settings = get_settings()
configure_logging("data-ingestion", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Data Ingestion Service", version="8.0.0")
install_internal_api_key_middleware(app)
install_prometheus_metrics(app, service_name="data-ingestion")
setup_tracing("data-ingestion", app)

_SOURCE_MODE = os.getenv("DATA_SOURCE_MODE", "simulator")
_UNIT_ID = int(os.getenv("DATA_UNIT_ID", "1"))
_UNIT_IDS = parse_unit_ids(os.getenv("DATA_UNIT_IDS"), default=[_UNIT_ID])
_SHARD_COUNT = max(1, int(os.getenv("INGESTION_SHARD_COUNT", "1")))
_SHARD_ID = resolve_shard_id(_SHARD_COUNT)
_ASSIGNED_UNITS = filter_units_for_shard(_UNIT_IDS, _SHARD_COUNT, _SHARD_ID)
_INGESTION_INTERVAL_S = float(os.getenv("INGESTION_INTERVAL_S", "1.0"))
_CIRCUIT_FAILURE_THRESHOLD = int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3"))
_CIRCUIT_RECOVERY_TIMEOUT_S = float(os.getenv("CIRCUIT_BREAKER_RECOVERY_TIMEOUT_S", "30"))
_HARDWARE_READ_TIMEOUT_S = float(os.getenv("HARDWARE_READ_TIMEOUT_S", "3"))
_INFLUX_BATCH_SIZE = int(os.getenv("INFLUX_BATCH_SIZE", "50"))

_backpressure = BackpressureController(
    high_watermark=int(os.getenv("BACKPRESSURE_HIGH", "1000")),
    low_watermark=int(os.getenv("BACKPRESSURE_LOW", "200")),
)

_state = {
    "running": False,
    "records_sent": 0,
    "records_buffered": 0,
    "records_from_hardware": 0,
    "records_from_fallback": 0,
    "source_mode": _SOURCE_MODE,
    "hardware_connected": False,
    "shard_id": _SHARD_ID,
    "shard_count": _SHARD_COUNT,
    "assigned_units": _ASSIGNED_UNITS,
    "backpressure_pauses": 0,
}


def _get_producer():
    from confluent_kafka import Producer

    cfg = high_throughput_producer_config(settings.kafka_bootstrap_servers, client_id=f"data-ingestion-{_SHARD_ID}")
    return Producer(cfg)


def _build_hardware_client(unit_mapping: UnitTagMapping):
    if _SOURCE_MODE == "opcua":
        return OpcUaClient(endpoint_url=unit_mapping.opcua.endpoint_url, node_ids=unit_mapping.opcua.nodes)
    if _SOURCE_MODE == "modbus":
        return ModbusClient(
            host=unit_mapping.modbus.host,
            port=unit_mapping.modbus.port,
            registers=unit_mapping.modbus.registers,
            scale=unit_mapping.modbus.scale,
        )
    return None


def _ready() -> bool:
    return bool(getattr(app.state, "producer", None)) and _state.get("running", False)


install_health_probes(
    app,
    service_name="data-ingestion",
    ready_check=_ready,
    details=lambda: {
        "shard_id": _SHARD_ID,
        "assigned_units": len(_ASSIGNED_UNITS),
        "records_sent": _state["records_sent"],
        "backpressure": _backpressure.as_dict(),
    },
)


@app.on_event("startup")
async def startup_event() -> None:
    app.state.buffer = LocalBuffer()
    try:
        app.state.influx_writer = InfluxRawWriter(
            url=settings.influxdb_url,
            token=settings.influxdb_token,
            org=settings.influxdb_org,
            bucket=settings.influxdb_bucket,
            batch_size=_INFLUX_BATCH_SIZE,
            use_async_batch=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("اتصال اولیه به InfluxDB ناموفق بود: %s", exc)
        app.state.influx_writer = None

    app.state.producer = _get_producer()
    app.state.simulator = SensorSimulator()
    app.state.circuit_breaker = CircuitBreaker(
        name=_SOURCE_MODE,
        failure_threshold=_CIRCUIT_FAILURE_THRESHOLD,
        recovery_timeout_s=_CIRCUIT_RECOVERY_TIMEOUT_S,
    )
    app.state.hardware_client = None

    if _SOURCE_MODE in ("opcua", "modbus"):
        try:
            mapping = load_tag_mapping()
            # سخت‌افزار معمولاً روی یک واحد؛ از اولین واحد تخصیص‌یافته استفاده می‌شود
            unit_id = _ASSIGNED_UNITS[0] if _ASSIGNED_UNITS else _UNIT_ID
            unit_mapping = mapping.get(unit_id) or mapping.get(_UNIT_ID)
            if unit_mapping is None:
                raise KeyError(f"نگاشت تگ برای واحد {unit_id} یافت نشد.")
            app.state.hardware_client = _build_hardware_client(unit_mapping)
        except Exception as exc:  # noqa: BLE001
            logger.error("بارگذاری نگاشت تگ ناموفق بود؛ Fallback به شبیه‌ساز: %s", exc)

    app.state.ingestion_task = asyncio.create_task(_ingestion_loop())
    logger.info(
        "Data Ingestion آماده شد mode=%s shard=%s/%s units=%s interval=%ss",
        _SOURCE_MODE,
        _SHARD_ID,
        _SHARD_COUNT,
        _ASSIGNED_UNITS,
        _INGESTION_INTERVAL_S,
    )


@app.on_event("shutdown")
async def shutdown_event() -> None:
    _state["running"] = False
    task = getattr(app.state, "ingestion_task", None)
    if task:
        task.cancel()
    if getattr(app.state, "influx_writer", None):
        app.state.influx_writer.close()
    hardware_client = getattr(app.state, "hardware_client", None)
    if hardware_client is not None and _state["hardware_connected"]:
        await hardware_client.disconnect() if hasattr(hardware_client, "disconnect") else None
    producer = getattr(app.state, "producer", None)
    if producer is not None:
        try:
            producer.flush(5)
        except Exception:  # noqa: BLE001
            pass


async def _ensure_hardware_connected() -> bool:
    breaker: CircuitBreaker = app.state.circuit_breaker
    if _state["hardware_connected"]:
        return True
    if not breaker.allow_request():
        return False
    try:
        await app.state.hardware_client.connect()
        _state["hardware_connected"] = True
        breaker.record_success()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("اتصال سخت‌افزاری (%s) ناموفق: %s", _SOURCE_MODE, exc)
        breaker.record_failure()
        _state["hardware_connected"] = False
        return False


async def _read_from_hardware(unit_id: int) -> dict | None:
    breaker: CircuitBreaker = app.state.circuit_breaker
    if not await _ensure_hardware_connected():
        return None
    try:
        values = await asyncio.wait_for(app.state.hardware_client.read_once(), timeout=_HARDWARE_READ_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        logger.error("خوانش سخت‌افزاری ناموفق: %s", exc)
        breaker.record_failure()
        _state["hardware_connected"] = False
        return None

    required_fields = ("reactor_temp_c", "reactor_pressure_bar", "feed_flow_m3h", "tank_level_percent")
    if not values or not all(field in values for field in required_fields):
        breaker.record_failure()
        return None

    breaker.record_success()
    from datetime import datetime, timezone

    return {"timestamp": datetime.now(timezone.utc), "unit_id": unit_id, **values}


async def _ingestion_loop() -> None:
    _state["running"] = True
    units = _ASSIGNED_UNITS or [_UNIT_ID]
    while _state["running"]:
        pending = app.state.buffer.pending_count() if hasattr(app.state, "buffer") else 0
        if _backpressure.update(pending):
            _state["backpressure_pauses"] = _backpressure.pause_events
            await asyncio.sleep(min(2.0, _INGESTION_INTERVAL_S * 2))
            _flush_local_buffer()
            continue

        batch_readings: list[dict] = []
        for unit_id in units:
            try:
                reading = None
                if _SOURCE_MODE in ("opcua", "modbus") and len(units) == 1:
                    reading = await _read_from_hardware(unit_id)
                    if reading is not None:
                        _state["records_from_hardware"] += 1

                if reading is None:
                    reading = app.state.simulator.next_reading(unit_id=unit_id)
                    if _SOURCE_MODE in ("opcua", "modbus"):
                        _state["records_from_fallback"] += 1

                batch_readings.append(reading)
            except Exception:  # noqa: BLE001
                logger.exception("خطا در تولید رکورد واحد %s", unit_id)

        if batch_readings:
            _dispatch_batch(batch_readings)

        await asyncio.sleep(_INGESTION_INTERVAL_S)


def _dispatch_batch(readings: list[dict]) -> None:
    producer = app.state.producer
    for reading in readings:
        payload = stamp_schema_metadata(
            {**reading, "timestamp": reading["timestamp"].isoformat()},
            SchemaName.RAW_SENSOR,
        )
        key = partition_key_for_unit(int(reading.get("unit_id", 1)))
        try:
            producer.produce(
                settings.kafka_topic_raw_sensors,
                key=key.encode("utf-8"),
                value=json.dumps(payload).encode("utf-8"),
            )
            _state["records_sent"] += 1
            inc_counter("khalij_ingestion_records_total", service="data-ingestion", labels={"source": _SOURCE_MODE})
        except BufferError:
            app.state.buffer.push(settings.kafka_topic_raw_sensors, payload)
            _state["records_buffered"] += 1

    producer.poll(0)

    if app.state.influx_writer is not None:
        try:
            app.state.influx_writer.write_batch(readings)
        except Exception:  # noqa: BLE001
            for reading in readings:
                try:
                    app.state.influx_writer.write_reading(reading)
                except Exception:  # noqa: BLE001
                    logger.debug("نوشتن Influx ناموفق بود.")

    _flush_local_buffer()


def _flush_local_buffer() -> None:
    for row_id, topic, payload in app.state.buffer.drain():
        try:
            unit_id = int(payload.get("unit_id", 1))
            app.state.producer.produce(
                topic,
                key=partition_key_for_unit(unit_id).encode("utf-8"),
                value=json.dumps(payload).encode("utf-8"),
            )
            app.state.producer.poll(0)
            app.state.buffer.remove(row_id)
        except BufferError:
            break


@app.get("/health")
async def health() -> dict:
    breaker: CircuitBreaker | None = getattr(app.state, "circuit_breaker", None)
    influx = getattr(app.state, "influx_writer", None)
    return {
        "status": "ok",
        "mode": _state["source_mode"],
        "hardware_connected": _state["hardware_connected"],
        "circuit_breaker": breaker.as_dict() if breaker else None,
        "records_sent": _state["records_sent"],
        "records_buffered_pending": app.state.buffer.pending_count() if hasattr(app.state, "buffer") else 0,
        "shard": {"id": _SHARD_ID, "count": _SHARD_COUNT, "units": _ASSIGNED_UNITS},
        "backpressure": _backpressure.as_dict(),
        "influx": influx.stats() if influx else None,
        "phase": 7,
    }


@app.get("/metrics/app")
async def metrics_app() -> dict:
    return {**_state, "backpressure": _backpressure.as_dict()}


@app.get("/scale/info")
async def scale_info() -> dict:
    return {
        "shard_id": _SHARD_ID,
        "shard_count": _SHARD_COUNT,
        "all_unit_ids": _UNIT_IDS,
        "assigned_units": _ASSIGNED_UNITS,
        "ingestion_interval_s": _INGESTION_INTERVAL_S,
        "kafka_topic": settings.kafka_topic_raw_sensors,
    }
