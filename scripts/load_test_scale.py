"""شبیه‌سازی بار برای مقیاس ۵۰k سنسور (فاز ۷ / NFR-SCL-01).

بدون نیاز به Docker کامل: تولید دسته‌ای رکورد خام و سنجش throughput تولیدکننده.

اجرا:
    python scripts/load_test_scale.py --units 1000 --seconds 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def synthesize(unit_id: int) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "unit_id": unit_id,
        "reactor_temp_c": 250.0,
        "reactor_pressure_bar": 25.0,
        "feed_flow_m3h": 300.0,
        "tank_level_percent": 50.0,
        "ethylene_conc_percent": 18.0,
        "compressor_rpm": 1500.0,
        "schema_name": "raw_sensor",
        "schema_version": "1.0",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Load test generator for Khalij POS scale phase")
    parser.add_argument("--units", type=int, default=1000, help="تعداد واحد/سنسور مجازی")
    parser.add_argument("--seconds", type=float, default=3.0, help="مدت تولید")
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--kafka", action="store_true", help="ارسال واقعی به Kafka (در غیر این صورت dry-run)")
    parser.add_argument("--bootstrap", default="localhost:29092")
    parser.add_argument("--topic", default="raw-sensor-data")
    args = parser.parse_args()

    from shared.scaling import partition_key_for_unit

    produced = 0
    t0 = time.perf_counter()
    deadline = t0 + args.seconds

    producer = None
    if args.kafka:
        from shared.kafka_utils import KafkaEventProducer

        producer = KafkaEventProducer(args.bootstrap, client_id="load-test-scale", high_throughput=True)

    unit = 1
    while time.perf_counter() < deadline:
        batch = []
        for _ in range(args.batch_size):
            batch.append(synthesize(((unit - 1) % args.units) + 1))
            unit += 1
        if producer:
            producer.send_batch(args.topic, batch, key_fn=lambda p: partition_key_for_unit(int(p["unit_id"])))
        else:
            # dry-run: serialize to measure CPU cost
            for item in batch:
                json.dumps(item)
        produced += len(batch)

    elapsed = time.perf_counter() - t0
    if producer:
        producer.flush(10)

    rps = produced / elapsed if elapsed else 0
    print(f"[OK] produced={produced} elapsed={elapsed:.2f}s rate={rps:.0f} msg/s units={args.units} kafka={args.kafka}")
    # هدف تقریبی برای مسیر ۵۰k سنسور @1Hz = 50k msg/s در کل خوشه؛ این تست تک‌process است
    target_hint = 50000
    print(f"hint: 50k sensors @1Hz needs ~{target_hint} msg/s cluster-wide; this process achieved {rps:.0f} msg/s")


if __name__ == "__main__":
    main()
