"""آموزش batch آفلاین از روی CSV سنتتیک یا داده تاریخی (فاز ۳).

مثال:
    python -m app.train_offline --csv ../../data/petrochemical_sensor_data_10k.csv
    python scripts/train_model.py --csv data/sample.csv --mlflow-uri http://localhost:5000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | train-offline | %(levelname)s | %(message)s")
logger = logging.getLogger("train-offline")


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch training + model comparison (Phase 3)")
    parser.add_argument("--csv", type=Path, required=True, help="مسیر CSV شامل ستون reactor_temp_c")
    parser.add_argument("--column", type=str, default="reactor_temp_c")
    parser.add_argument("--mlflow-uri", type=str, default="http://localhost:5000")
    parser.add_argument("--n-lags", type=int, default=10)
    parser.add_argument("--horizon", type=int, default=60)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    # اضافه کردن مسیر سرویس به PYTHONPATH
    service_root = Path(__file__).resolve().parents[1]
    repo_root = service_root.parents[1]
    sys.path.insert(0, str(service_root))
    sys.path.insert(0, str(repo_root))

    from app.training_pipeline import TrainingPipeline

    df = pd.read_csv(args.csv)
    if args.limit > 0:
        df = df.head(args.limit)
    if args.column not in df.columns:
        logger.error("ستون %s در CSV نیست. ستون‌ها: %s", args.column, list(df.columns))
        return 1

    series = df[args.column].astype(float).tolist()
    logger.info("شروع آموزش روی %d نمونه از %s", len(series), args.csv)

    pipeline = TrainingPipeline(
        mlflow_tracking_uri=args.mlflow_uri,
        n_lags=args.n_lags,
        horizon=args.horizon,
    )
    result = pipeline.train_and_select(series, promote_to_production=True)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
