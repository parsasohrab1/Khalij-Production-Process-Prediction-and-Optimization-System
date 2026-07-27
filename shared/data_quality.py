"""قوانین کیفیت داده (Data Quality) برای سنسورهای فرایند — فاز ۲.

الهام‌گرفته از Great Expectations، بدون وابستگی سنگین خارجی.
هر Expectation روی یک رکورد یا دسته رکورد اجرا می‌شود و نتیجه Pass/Fail برمی‌گرداند.
"""
from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import datetime, timezone
from typing import Any, Callable

# محدوده فیزیکی مجاز مطابق FR-DATA-02 / SRS
SENSOR_BOUNDS: dict[str, tuple[float, float]] = {
    "reactor_temp_c": (150.0, 350.0),
    "reactor_pressure_bar": (10.0, 40.0),
    "feed_flow_m3h": (100.0, 500.0),
    "tank_level_percent": (20.0, 85.0),
    "ethylene_conc_percent": (12.0, 25.0),
    "compressor_rpm": (1200.0, 1800.0),
}

REQUIRED_FIELDS = (
    "timestamp",
    "unit_id",
    "reactor_temp_c",
    "reactor_pressure_bar",
    "feed_flow_m3h",
    "tank_level_percent",
    "ethylene_conc_percent",
    "compressor_rpm",
)


@dataclass
class ExpectationResult:
    name: str
    success: bool
    detail: str = ""
    observed: Any = None


@dataclass
class QualityReport:
    passed: bool
    results: list[ExpectationResult] = dc_field(default_factory=list)
    checked_at: str = dc_field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def failures(self) -> list[ExpectationResult]:
        return [r for r in self.results if not r.success]


def expect_required_fields(record: dict) -> ExpectationResult:
    missing = [f for f in REQUIRED_FIELDS if f not in record or record[f] is None]
    return ExpectationResult(
        name="expect_required_fields",
        success=len(missing) == 0,
        detail=f"missing={missing}" if missing else "all required fields present",
        observed=missing,
    )


def expect_value_in_range(record: dict, field: str, low: float, high: float) -> ExpectationResult:
    value = record.get(field)
    if value is None:
        return ExpectationResult(name=f"expect_{field}_in_range", success=False, detail="value is None", observed=None)
    try:
        num = float(value)
    except (TypeError, ValueError):
        return ExpectationResult(
            name=f"expect_{field}_in_range", success=False, detail="not a number", observed=value
        )
    ok = low <= num <= high
    return ExpectationResult(
        name=f"expect_{field}_in_range",
        success=ok,
        detail=f"expected [{low}, {high}], got {num}",
        observed=num,
    )


def expect_freshness(record: dict, max_age_seconds: float = 10.0) -> ExpectationResult:
    """بررسی اینکه timestamp رکورد بیش از حد قدیمی نباشد (تأخیر خط لوله)."""
    ts = record.get("timestamp")
    if ts is None:
        return ExpectationResult(name="expect_freshness", success=False, detail="timestamp missing")
    try:
        if isinstance(ts, str):
            parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            parsed = ts
        else:
            return ExpectationResult(name="expect_freshness", success=False, detail="invalid timestamp type")
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed).total_seconds()
        # برای داده تاریخی/سنتتیک سن را محدود نمی‌کنیم اگر منفی یا خیلی بزرگ باشد در حالت batch
        ok = age <= max_age_seconds or age < 0
        return ExpectationResult(
            name="expect_freshness",
            success=ok,
            detail=f"age_seconds={age:.2f}, max={max_age_seconds}",
            observed=age,
        )
    except Exception as exc:  # noqa: BLE001
        return ExpectationResult(name="expect_freshness", success=False, detail=str(exc))


def expect_null_rate(records: list[dict], field: str, max_null_rate: float = 0.05) -> ExpectationResult:
    if not records:
        return ExpectationResult(name=f"expect_null_rate_{field}", success=True, detail="empty batch")
    nulls = sum(1 for r in records if r.get(field) is None)
    rate = nulls / len(records)
    return ExpectationResult(
        name=f"expect_null_rate_{field}",
        success=rate <= max_null_rate,
        detail=f"null_rate={rate:.3f}, max={max_null_rate}",
        observed=rate,
    )


def validate_record(
    record: dict,
    *,
    check_freshness: bool = False,
    max_age_seconds: float = 10.0,
) -> QualityReport:
    """اجرای مجموعه Expectationها روی یک رکورد سنسور."""
    results: list[ExpectationResult] = [expect_required_fields(record)]
    for sensor_field, (low, high) in SENSOR_BOUNDS.items():
        results.append(expect_value_in_range(record, sensor_field, low, high))
    if check_freshness:
        results.append(expect_freshness(record, max_age_seconds=max_age_seconds))
    return QualityReport(passed=all(r.success for r in results), results=results)


def validate_batch(records: list[dict], max_null_rate: float = 0.05) -> QualityReport:
    """اجرای Expectationهای دسته‌ای (نرخ NaN و محدوده روی هر رکورد)."""
    results: list[ExpectationResult] = []
    for sensor_field in SENSOR_BOUNDS:
        results.append(expect_null_rate(records, sensor_field, max_null_rate=max_null_rate))
    for i, record in enumerate(records):
        report = validate_record(record, check_freshness=False)
        for r in report.failures:
            results.append(
                ExpectationResult(
                    name=f"row_{i}_{r.name}",
                    success=False,
                    detail=r.detail,
                    observed=r.observed,
                )
            )
    # اگر هیچ failure ردیفی نباشد، یک نتیجه کلی موفق اضافه می‌کنیم
    row_failures = [r for r in results if r.name.startswith("row_")]
    if not row_failures:
        results.append(ExpectationResult(name="expect_all_rows_valid", success=True, detail=f"n={len(records)}"))
    return QualityReport(passed=all(r.success for r in results), results=results)


# رجیستری expectationهای قابل فراخوانی از CLI
EXPECTATION_SUITE: list[Callable[..., ExpectationResult]] = [
    expect_required_fields,
]
