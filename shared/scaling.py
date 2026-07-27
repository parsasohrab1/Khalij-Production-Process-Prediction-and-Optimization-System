"""ابزار مقیاس‌پذیری افقی و اندازه‌گیری تأخیر (فاز ۷ / NFR-SCL-01, NFR-PER-01)."""
from __future__ import annotations

import hashlib
import os
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field


def parse_unit_ids(spec: str | None, default: list[int] | None = None) -> list[int]:
    """پارس لیست واحدها: '1,2,3' یا '1-50' یا ترکیب '1-10,20,30-32'."""
    if not spec or not spec.strip():
        return list(default or [1])
    units: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
            if end < start:
                start, end = end, start
            units.update(range(start, end + 1))
        else:
            units.add(int(part))
    return sorted(units) if units else list(default or [1])


def resolve_shard_id(shard_count: int, explicit: int | None = None) -> int:
    """شناسه شارد این نمونه؛ از env یا هش hostname."""
    if explicit is not None:
        return int(explicit) % max(1, shard_count)
    raw = os.getenv("INGESTION_SHARD_ID") or os.getenv("SHARD_ID")
    if raw is not None and str(raw).strip() != "":
        return int(raw) % max(1, shard_count)
    host = os.getenv("HOSTNAME") or socket.gethostname()
    digest = hashlib.md5(host.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(1, shard_count)


def filter_units_for_shard(unit_ids: list[int], shard_count: int, shard_id: int) -> list[int]:
    """تخصیص پایدار واحدها به شاردها برای مقیاس افقی ingestion."""
    if shard_count <= 1:
        return list(unit_ids)
    return [u for u in unit_ids if u % shard_count == shard_id]


def partition_key_for_unit(unit_id: int) -> str:
    """کلید پارتیشن Kafka بر اساس unit_id برای توزیع یکنواخت."""
    return f"unit:{unit_id}"


@dataclass
class LatencyTracker:
    """ردیاب تأخیر برای بودجه NFR-PER-01 (< ۲ ثانیه)."""

    budget_ms: float = 2000.0
    window: int = 500
    _samples: deque = field(default_factory=lambda: deque(maxlen=500))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    violations: int = 0
    total: int = 0

    def __post_init__(self) -> None:
        self._samples = deque(maxlen=self.window)

    def record(self, elapsed_ms: float) -> None:
        with self._lock:
            self._samples.append(float(elapsed_ms))
            self.total += 1
            if elapsed_ms > self.budget_ms:
                self.violations += 1

    def measure(self):
        tracker = self

        class _Ctx:
            def __enter__(self_inner):
                self_inner._t0 = time.perf_counter()
                return self_inner

            def __exit__(self_inner, *args):
                ms = (time.perf_counter() - self_inner._t0) * 1000.0
                tracker.record(ms)
                self_inner.elapsed_ms = ms

        return _Ctx()

    def snapshot(self) -> dict:
        with self._lock:
            samples = list(self._samples)
        if not samples:
            return {
                "count": 0,
                "avg_ms": None,
                "p50_ms": None,
                "p95_ms": None,
                "p99_ms": None,
                "max_ms": None,
                "budget_ms": self.budget_ms,
                "violations": self.violations,
                "within_budget_ratio": 1.0,
            }
        ordered = sorted(samples)

        def pct(p: float) -> float:
            idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
            return round(ordered[idx], 3)

        return {
            "count": len(samples),
            "avg_ms": round(sum(samples) / len(samples), 3),
            "p50_ms": pct(50),
            "p95_ms": pct(95),
            "p99_ms": pct(99),
            "max_ms": round(max(samples), 3),
            "budget_ms": self.budget_ms,
            "violations": self.violations,
            "total_recorded": self.total,
            "within_budget_ratio": round(1.0 - (self.violations / max(1, self.total)), 4),
        }


@dataclass
class BackpressureController:
    """بک‌پرشر ساده وقتی صف Kafka/بافر محلی پر می‌شود."""

    high_watermark: int = 1000
    low_watermark: int = 200
    _paused: bool = False
    pause_events: int = 0

    def update(self, queue_depth: int) -> bool:
        """True اگر باید تولید/خوانش کند شود."""
        if queue_depth >= self.high_watermark:
            if not self._paused:
                self.pause_events += 1
            self._paused = True
        elif queue_depth <= self.low_watermark:
            self._paused = False
        return self._paused

    @property
    def paused(self) -> bool:
        return self._paused

    def as_dict(self) -> dict:
        return {
            "paused": self._paused,
            "high_watermark": self.high_watermark,
            "low_watermark": self.low_watermark,
            "pause_events": self.pause_events,
        }
