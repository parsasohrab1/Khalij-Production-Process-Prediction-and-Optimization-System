"""شبیه‌ساز سنسورها برای محیط توسعه/دمو (بدون نیاز به سرور OPC-UA/Modbus واقعی).

الگوی نوسانی و نویز مشابه اسکریپت data/generate_synthetic_data.py استفاده می‌شود
تا رفتار خط لوله داده (Ingestion -> Kafka -> Preprocessing -> Prediction) قابل تست باشد.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

import numpy as np


class SensorSimulator:
    """در هر فراخوانی `next_reading`، یک رکورد سنسور جدید (مطابق FR-DATA-02) تولید می‌کند."""

    def __init__(self, seed: int | None = None):
        self._rng = np.random.default_rng(seed)
        self._t0 = time.monotonic()

    def next_reading(self, unit_id: int = 1) -> dict:
        elapsed = time.monotonic() - self._t0
        # فاز هر واحد کمی جابه‌جا می‌شود تا شاردهای موازی داده یکسان تولید نکنند
        t = elapsed * 0.05 + (unit_id % 17) * 0.37

        reactor_temp = 250 + 30 * math.sin(t * 0.5) + 0.0005 * elapsed + self._rng.normal(0, 2)
        pressure = 25 + 5 * math.sin(t * 0.3) + 0.0002 * elapsed + self._rng.normal(0, 0.8)
        feed_flow = 300 + 80 * math.sin(t * 0.2 + 1.2) + self._rng.normal(0, 5)
        tank_level = 50 + 20 * math.sin(t * 0.15 + 2.5) + self._rng.normal(0, 1.5)
        ethylene_conc = 18 + 3 * math.sin(t * 0.25 + 0.8) + 0.0001 * elapsed + self._rng.normal(0, 0.5)
        compressor_rpm = 1500 + 150 * math.sin(t * 0.1 + 3.0) + self._rng.normal(0, 10)

        return {
            "timestamp": datetime.now(timezone.utc),
            "unit_id": unit_id,
            "reactor_temp_c": round(float(np.clip(reactor_temp, 150, 350)), 2),
            "reactor_pressure_bar": round(float(np.clip(pressure, 10, 40)), 2),
            "feed_flow_m3h": round(float(np.clip(feed_flow, 100, 500)), 2),
            "tank_level_percent": round(float(np.clip(tank_level, 20, 85)), 2),
            "ethylene_conc_percent": round(float(np.clip(ethylene_conc, 12, 25)), 2),
            "compressor_rpm": round(float(np.clip(compressor_rpm, 1200, 1800)), 0),
        }
