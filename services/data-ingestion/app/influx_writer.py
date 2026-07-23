"""نوشتن داده خام سنسورها در InfluxDB برای نگهداری ۵ ساله (R-GEN-02)."""
from __future__ import annotations

import logging

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

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
    def __init__(self, url: str, token: str, org: str, bucket: str):
        self._client = InfluxDBClient(url=url, token=token, org=org)
        self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
        self._bucket = bucket
        self._org = org

    def write_reading(self, reading: dict, measurement: str = "raw_sensor_data") -> None:
        point = (
            Point(measurement)
            .tag("unit_id", str(reading.get("unit_id", 1)))
            .time(reading["timestamp"], WritePrecision.S)
        )
        for field in _SENSOR_FIELDS:
            if field in reading and reading[field] is not None:
                point = point.field(field, float(reading[field]))
        try:
            self._write_api.write(bucket=self._bucket, org=self._org, record=point)
        except Exception as exc:  # noqa: BLE001
            logger.error("نوشتن در InfluxDB ناموفق بود: %s", exc)
            raise

    def close(self) -> None:
        self._client.close()
