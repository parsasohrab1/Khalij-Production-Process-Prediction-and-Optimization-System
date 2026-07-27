"""نوشتن داده خام سنسورها در InfluxDB برای نگهداری ۵ ساله (R-GEN-02).

فاز ۷: نوشتن دسته‌ای (batch) برای throughput بالاتر.
"""
from __future__ import annotations

import logging
import threading
import time

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS, WriteOptions

logger = logging.getLogger(__name__)

_SENSOR_FIELDS = (
    "reactor_temp_c",
    "reactor_pressure_bar",
    "feed_flow_m3h",
    "tank_level_percent",
    "ethylene_conc_percent",
    "compressor_rpm",
)


class InfluxRawWriter:
    def __init__(
        self,
        url: str,
        token: str,
        org: str,
        bucket: str,
        *,
        batch_size: int = 50,
        flush_interval_s: float = 1.0,
        use_async_batch: bool = True,
    ):
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._bucket = bucket
        self._org = org
        self._batch_size = max(1, batch_size)
        self._flush_interval_s = flush_interval_s
        self._lock = threading.Lock()
        self._buffer: list[Point] = []
        self._last_flush = time.monotonic()
        self._written = 0
        self._flushes = 0
        self._errors = 0

        if use_async_batch:
            self._write_api = self._client.write_api(
                write_options=WriteOptions(
                    batch_size=batch_size,
                    flush_interval=int(flush_interval_s * 1000),
                    jitter_interval=200,
                    retry_interval=1000,
                )
            )
            self._mode = "async_batch"
        else:
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._mode = "sync"

    def _to_point(self, reading: dict, measurement: str = "raw_sensor_data") -> Point:
        point = (
            Point(measurement)
            .tag("unit_id", str(reading.get("unit_id", 1)))
            .time(reading["timestamp"], WritePrecision.S)
        )
        for field in _SENSOR_FIELDS:
            if field in reading and reading[field] is not None:
                point = point.field(field, float(reading[field]))
        return point

    def write_reading(self, reading: dict, measurement: str = "raw_sensor_data") -> None:
        point = self._to_point(reading, measurement)
        if self._mode == "async_batch":
            try:
                self._write_api.write(bucket=self._bucket, org=self._org, record=point)
                self._written += 1
            except Exception as exc:  # noqa: BLE001
                self._errors += 1
                logger.error("نوشتن async در InfluxDB ناموفق بود: %s", exc)
                raise
            return

        with self._lock:
            self._buffer.append(point)
            should_flush = len(self._buffer) >= self._batch_size or (
                time.monotonic() - self._last_flush >= self._flush_interval_s
            )
        if should_flush:
            self.flush()

    def write_batch(self, readings: list[dict], measurement: str = "raw_sensor_data") -> int:
        points = [self._to_point(r, measurement) for r in readings]
        try:
            self._write_api.write(bucket=self._bucket, org=self._org, record=points)
            self._written += len(points)
            self._flushes += 1
            return len(points)
        except Exception as exc:  # noqa: BLE001
            self._errors += 1
            logger.error("نوشتن batch در InfluxDB ناموفق بود: %s", exc)
            raise

    def flush(self) -> int:
        with self._lock:
            if not self._buffer:
                return 0
            points = self._buffer
            self._buffer = []
            self._last_flush = time.monotonic()
        try:
            self._write_api.write(bucket=self._bucket, org=self._org, record=points)
            self._written += len(points)
            self._flushes += 1
            return len(points)
        except Exception as exc:  # noqa: BLE001
            self._errors += 1
            logger.error("flush InfluxDB ناموفق بود: %s", exc)
            with self._lock:
                self._buffer = points + self._buffer
            raise

    def stats(self) -> dict:
        with self._lock:
            pending = len(self._buffer)
        return {
            "mode": self._mode,
            "written": self._written,
            "flushes": self._flushes,
            "errors": self._errors,
            "pending": pending,
            "batch_size": self._batch_size,
        }

    def close(self) -> None:
        try:
            if self._mode == "sync":
                self.flush()
            self._write_api.close()
        except Exception:  # noqa: BLE001
            pass
        self._client.close()
