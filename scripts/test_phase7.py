"""تست‌های واحد فاز ۷: مقیاس‌پذیری و کارایی (NFR-SCL-01 / NFR-PER-01).

اجرا:
    python scripts/test_phase7.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_parse_and_shard() -> None:
    from shared.scaling import filter_units_for_shard, parse_unit_ids, partition_key_for_unit, resolve_shard_id

    units = parse_unit_ids("1-10,20,30-32")
    assert units == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 31, 32]
    shard0 = filter_units_for_shard(list(range(1, 13)), shard_count=3, shard_id=0)
    shard1 = filter_units_for_shard(list(range(1, 13)), shard_count=3, shard_id=1)
    shard2 = filter_units_for_shard(list(range(1, 13)), shard_count=3, shard_id=2)
    assert set(shard0 + shard1 + shard2) == set(range(1, 13))
    assert not (set(shard0) & set(shard1))
    assert resolve_shard_id(4, explicit=5) == 1
    assert partition_key_for_unit(42) == "unit:42"
    print(f"[OK] sharding units shard0={shard0}")


def test_latency_budget() -> None:
    from shared.scaling import LatencyTracker

    tracker = LatencyTracker(budget_ms=2000, window=100)
    for ms in (10, 20, 30, 1500, 2100):
        tracker.record(ms)
    snap = tracker.snapshot()
    assert snap["count"] == 5
    assert snap["violations"] == 1
    assert snap["p50_ms"] is not None
    assert snap["within_budget_ratio"] == 0.8
    with tracker.measure() as ctx:
        time.sleep(0.01)
    assert ctx.elapsed_ms >= 8
    print(f"[OK] latency tracker p95={snap['p95_ms']}ms violations={snap['violations']}")


def test_backpressure() -> None:
    from shared.scaling import BackpressureController

    bp = BackpressureController(high_watermark=10, low_watermark=3)
    assert bp.update(11) is True
    assert bp.paused is True
    assert bp.update(5) is True  # هنوز بالای low
    assert bp.update(2) is False
    assert bp.pause_events >= 1
    print("[OK] backpressure controller")


def test_kafka_high_throughput_config() -> None:
    from shared.kafka_utils import high_throughput_consumer_config, high_throughput_producer_config

    p = high_throughput_producer_config("kafka:9092", "test")
    assert p["compression.type"] in {"lz4", "snappy", "gzip", "zstd", "none"}
    assert int(p["linger.ms"]) >= 0
    assert int(p["batch.size"]) >= 1024
    c = high_throughput_consumer_config("kafka:9092", "g1")
    assert "fetch.min.bytes" in c
    print("[OK] kafka high-throughput config")


def test_health_module() -> None:
    from fastapi import FastAPI

    from shared.health import install_health_probes

    app = FastAPI()
    install_health_probes(app, service_name="demo", ready_check=lambda: True)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/health/live" in paths
    assert "/health/ready" in paths
    print("[OK] health probes")


def test_compose_scale_file() -> None:
    scale = (ROOT / "docker-compose.scale.yml").read_text(encoding="utf-8")
    assert "INGESTION_SHARD_COUNT" in scale
    assert "data-ingestion" in scale
    main = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "KAFKA_PARTITIONS" in main
    assert "container_name: khalij-data-ingestion" not in main
    print("[OK] compose scale artifacts")


def test_influx_batch_api() -> None:
    import importlib.util

    path = ROOT / "services" / "data-ingestion" / "app" / "influx_writer.py"
    spec = importlib.util.spec_from_file_location("phase7_influx_writer", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod.InfluxRawWriter, "write_batch")
    assert hasattr(mod.InfluxRawWriter, "stats")
    print("[OK] influx batch writer API")


if __name__ == "__main__":
    test_parse_and_shard()
    test_latency_budget()
    test_backpressure()
    test_kafka_high_throughput_config()
    test_health_module()
    test_compose_scale_file()
    test_influx_batch_api()
    print("\nفاز ۷: همه تست‌های واحد پاس شدند.")
