"""CLI کیفیت داده (فاز ۲) — اجرای Expectation Suite روی CSV یا JSON.

مثال‌ها:
    python -m data_quality.cli --csv data/petrochemical_sensor_data_10k.csv
    python -m data_quality.cli --json-line '{"timestamp":"...","reactor_temp_c":250,...}'
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

# اجازه import از ریشه پروژه
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.data_quality import validate_batch, validate_record  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Data Quality Expectation Suite (Phase 2)")
    parser.add_argument("--csv", type=Path, help="مسیر فایل CSV داده سنسور")
    parser.add_argument("--json-line", type=str, help="یک رکورد JSON برای اعتبارسنجی")
    parser.add_argument("--max-null-rate", type=float, default=0.05)
    parser.add_argument("--limit", type=int, default=0, help="حداکثر تعداد ردیف از CSV (0=همه)")
    args = parser.parse_args()

    if args.json_line:
        record = json.loads(args.json_line)
        report = validate_record(record, check_freshness=False)
        print(json.dumps({"passed": report.passed, "results": [r.__dict__ for r in report.results]}, ensure_ascii=False, indent=2))
        return 0 if report.passed else 1

    if args.csv:
        df = pd.read_csv(args.csv)
        if args.limit > 0:
            df = df.head(args.limit)
        records = df.to_dict(orient="records")
        report = validate_batch(records, max_null_rate=args.max_null_rate)
        failures = report.failures
        print(f"passed={report.passed} rows={len(records)} failures={len(failures)}")
        for f in failures[:20]:
            print(f"  - {f.name}: {f.detail}")
        if len(failures) > 20:
            print(f"  ... and {len(failures) - 20} more")
        return 0 if report.passed else 1

    parser.error("یکی از --csv یا --json-line لازم است.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
