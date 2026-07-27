"""راه‌اندازی bucketهای InfluxDB و Taskهای Downsampling (فاز ۲ / R-GEN-02).

استراتژی نگهداری داده:
  - process_sensors (hot): داده خام ثانیه‌ای، نگهداری ۳۰ روز
  - process_sensors_1m (cold): میانگین ۱ دقیقه‌ای، نگهداری ۵ سال (1825 روز)

این اسکریپت پس از healthy شدن InfluxDB اجرا می‌شود (سرویس influxdb-init در compose).
"""
from __future__ import annotations

import logging
import os
import sys
import time

from influxdb_client import InfluxDBClient, Task
from influxdb_client.domain.bucket_retention_rules import BucketRetentionRules
from influxdb_client.rest import ApiException

logging.basicConfig(level=logging.INFO, format="%(asctime)s | influx-init | %(levelname)s | %(message)s")
logger = logging.getLogger("influx-init")

URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
TOKEN = os.getenv("INFLUXDB_TOKEN", "")
ORG = os.getenv("INFLUXDB_ORG", "khalij-holding")
HOT_BUCKET = os.getenv("INFLUXDB_BUCKET", "process_sensors")
COLD_BUCKET = os.getenv("INFLUXDB_BUCKET_DOWNSAMPLED", "process_sensors_1m")
HOT_RETENTION = os.getenv("INFLUXDB_HOT_RETENTION", "30d")
COLD_RETENTION = os.getenv("INFLUXDB_RETENTION", "1825d")


def _parse_duration_seconds(value: str) -> int:
    value = value.strip().lower()
    if value.endswith("d"):
        return int(value[:-1]) * 86400
    if value.endswith("h"):
        return int(value[:-1]) * 3600
    if value.endswith("m"):
        return int(value[:-1]) * 60
    return int(value)


DOWNSAMPLE_FLUX = """
option task = {{name: "downsample_raw_to_1m", every: 1m}}

from(bucket: "{hot}")
  |> range(start: -2m)
  |> filter(fn: (r) => r._measurement == "raw_sensor_data" or r._measurement == "processed_sensor_data")
  |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
  |> set(key: "_measurement", value: "sensor_data_1m")
  |> to(bucket: "{cold}", org: "{org}")
"""


def wait_for_influx(client: InfluxDBClient, retries: int = 30) -> None:
    for i in range(retries):
        try:
            if client.ping():
                logger.info("InfluxDB آماده است.")
                return
        except Exception:  # noqa: BLE001
            pass
        logger.info("در انتظار InfluxDB... (%s/%s)", i + 1, retries)
        time.sleep(2)
    raise RuntimeError("InfluxDB در زمان مقرر آماده نشد.")


def ensure_bucket(buckets_api, org_id: str, name: str, retention: str) -> None:
    existing = buckets_api.find_bucket_by_name(name)
    every_seconds = _parse_duration_seconds(retention)
    if existing:
        logger.info("Bucket '%s' از قبل وجود دارد.", name)
        return
    rules = [BucketRetentionRules(type="expire", every_seconds=every_seconds)]
    buckets_api.create_bucket(bucket_name=name, org_id=org_id, retention_rules=rules)
    logger.info("Bucket '%s' با retention=%s ساخته شد.", name, retention)


def ensure_downsample_task(tasks_api, org_id: str) -> None:
    flux = DOWNSAMPLE_FLUX.format(hot=HOT_BUCKET, cold=COLD_BUCKET, org=ORG)
    try:
        tasks = tasks_api.find_tasks(name="downsample_raw_to_1m")
        if tasks:
            logger.info("Task downsampling از قبل وجود دارد.")
            return
    except ApiException:
        pass
    task = Task(name="downsample_raw_to_1m", org_id=org_id, flux=flux, status="active")
    tasks_api.create_task(task)
    logger.info("Task downsampling (هر ۱ دقیقه) ساخته شد.")


def main() -> int:
    if not TOKEN:
        logger.error("INFLUXDB_TOKEN تنظیم نشده است.")
        return 1
    client = InfluxDBClient(url=URL, token=TOKEN, org=ORG)
    wait_for_influx(client)

    orgs = client.organizations_api().find_organizations(org=ORG)
    if not orgs:
        logger.error("سازمان '%s' یافت نشد.", ORG)
        return 1
    org_id = orgs[0].id

    buckets_api = client.buckets_api()
    # bucket اصلی توسط DOCKER_INFLUXDB_INIT ساخته می‌شود؛ cold bucket را اینجا می‌سازیم
    ensure_bucket(buckets_api, org_id, COLD_BUCKET, COLD_RETENTION)

    # اگر hot bucket با retention پنج‌ساله ساخته شده، هشدار می‌دهیم (باید ۳۰ روز باشد)
    hot = buckets_api.find_bucket_by_name(HOT_BUCKET)
    if hot:
        logger.info(
            "Bucket hot '%s' موجود است — توصیه: retention=%s (داده ثانیه‌ای).",
            HOT_BUCKET,
            HOT_RETENTION,
        )

    ensure_downsample_task(client.tasks_api(), org_id)
    client.close()
    logger.info("راه‌اندازی InfluxDB فاز ۲ کامل شد.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
