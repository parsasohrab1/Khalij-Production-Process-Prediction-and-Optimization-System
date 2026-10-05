"""Phase 2 unit tests: Schema Registry, Data Quality, DLQ envelope.

Run:
    python scripts/test_phase2.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.data_quality import validate_batch, validate_record  # noqa: E402
from shared.schema_registry import (  # noqa: E402
    SchemaName,
    SchemaValidationError,
    get_schema_version,
    stamp_schema_metadata,
    try_validate,
    validate_message,
)


def _valid_reading() -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "unit_id": 1,
        "reactor_temp_c": 250.1,
        "reactor_pressure_bar": 25.0,
        "feed_flow_m3h": 300.0,
        "tank_level_percent": 50.0,
        "ethylene_conc_percent": 18.0,
        "compressor_rpm": 1500,
    }


def test_schema_registry() -> None:
    assert get_schema_version(SchemaName.RAW_SENSOR) == "1.0.0"
    stamped = stamp_schema_metadata(_valid_reading(), SchemaName.RAW_SENSOR)
    assert stamped["_schema"] == "raw-sensor-data"
    assert stamped["_schema_version"] == "1.0.0"
    model = validate_message(stamped, SchemaName.RAW_SENSOR)
    assert model.reactor_temp_c == 250.1

    bad = _valid_reading()
    del bad["reactor_temp_c"]
    _, err = try_validate(bad, SchemaName.RAW_SENSOR)
    assert err is not None
    assert isinstance(err, SchemaValidationError)
    print("[OK] Schema Registry")


def test_data_quality() -> None:
    ok = validate_record(_valid_reading(), check_freshness=False)
    assert ok.passed

    out_of_range = _valid_reading()
    out_of_range["reactor_temp_c"] = 999.0
    report = validate_record(out_of_range, check_freshness=False)
    assert not report.passed
    assert any("reactor_temp_c" in f.name for f in report.failures)

    missing = _valid_reading()
    del missing["feed_flow_m3h"]
    report2 = validate_record(missing, check_freshness=False)
    assert not report2.passed

    batch = validate_batch([_valid_reading(), _valid_reading()])
    assert batch.passed
    print("[OK] Data Quality expectations")


def test_processed_schema() -> None:
    processed = {
        **_valid_reading(),
        "is_outlier_corrected": False,
        "is_interpolated": False,
        "normalized": {"reactor_temp_c": 0.5},
    }
    model, err = try_validate(processed, SchemaName.PROCESSED_SENSOR)
    assert err is None and model is not None
    print("[OK] Processed schema")


if __name__ == "__main__":
    test_schema_registry()
    test_data_quality()
    test_processed_schema()
    print("\nAll Phase-2 tests passed.")
