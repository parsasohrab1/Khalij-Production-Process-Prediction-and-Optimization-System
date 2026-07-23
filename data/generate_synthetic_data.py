"""
تولید داده‌های سنتتیک (شبیه‌سازی‌شده) سنسورهای فرایند تولید پتروشیمی.

این اسکریپت ۱۰,۰۰۰ رکورد برای هر یک از ۷ متغیر کلیدی با نرخ ۱ رکورد در ثانیه
تولید می‌کند (الگوهای سینوسی + روند + نویز گاوسی) و در یک فایل CSV ذخیره می‌کند.
از این داده برای آموزش اولیه مدل‌های پیش‌بینی و تست خط لوله پیش‌پردازش استفاده می‌شود.

اجرا:
    python data/generate_synthetic_data.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# در کنسول ویندوز (cp1256/cp1252) چاپ مستقیم متن فارسی خطای UnicodeEncodeError می‌دهد
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def generate_dataset(num_records: int, start_time: datetime, seed: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    timestamps = [start_time + timedelta(seconds=i) for i in range(num_records)]
    t = np.linspace(0, 20 * np.pi, num_records)

    # ۱. دمای راکتور (Reactor Temperature) - محدوده 150 تا 350 درجه سانتی‌گراد
    reactor_temp = 250 + 30 * np.sin(t * 0.5) + 0.01 * np.arange(num_records) + rng.normal(0, 2, num_records)
    reactor_temp = np.clip(reactor_temp, 150, 350)

    # ۲. فشار راکتور (Reactor Pressure) - محدوده 10 تا 40 بار
    pressure = 25 + 5 * np.sin(t * 0.3) + 0.005 * np.arange(num_records) + rng.normal(0, 0.8, num_records)
    pressure = np.clip(pressure, 10, 40)

    # ۳. دبی جریان خوراک ورودی (Feed Flow) - محدوده 100 تا 500 مترمکعب بر ساعت
    feed_flow = 300 + 80 * np.sin(t * 0.2 + 1.2) + rng.normal(0, 5, num_records)
    feed_flow = np.clip(feed_flow, 100, 500)

    # ۴. سطح مخزن (Tank Level) - محدوده 20 تا 85 درصد
    tank_level = 50 + 20 * np.sin(t * 0.15 + 2.5) + rng.normal(0, 1.5, num_records)
    tank_level = np.clip(tank_level, 20, 85)

    # ۵. ترکیب گاز خروجی (Ethylene Concentration) - محدوده 12 تا 25 درصد
    ethylene_conc = 18 + 3 * np.sin(t * 0.25 + 0.8) + 0.002 * np.arange(num_records) + rng.normal(0, 0.5, num_records)
    ethylene_conc = np.clip(ethylene_conc, 12, 25)

    # ۶. دور کمپرسور (Compressor RPM) - محدوده 1200 تا 1800 دور بر دقیقه
    compressor_rpm = 1500 + 150 * np.sin(t * 0.1 + 3.0) + rng.normal(0, 10, num_records)
    compressor_rpm = np.clip(compressor_rpm, 1200, 1800)

    # ۷. راندمان تولید (Production Efficiency) - متغیر هدف، تابعی از دما و فشار
    efficiency = (
        (reactor_temp - 200) / 150 * 20 + (pressure - 20) / 20 * 10 + 60 + rng.normal(0, 2, num_records)
    )
    efficiency = np.clip(efficiency, 40, 98)

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "reactor_temp_c": np.round(reactor_temp, 2),
            "reactor_pressure_bar": np.round(pressure, 2),
            "feed_flow_m3h": np.round(feed_flow, 2),
            "tank_level_percent": np.round(tank_level, 2),
            "ethylene_conc_percent": np.round(ethylene_conc, 2),
            "compressor_rpm": np.round(compressor_rpm, 0).astype(int),
            "efficiency_target": np.round(efficiency, 2),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="تولید داده سنتتیک سنسورهای فرایند تولید")
    parser.add_argument("--num-records", type=int, default=10_000, help="تعداد رکورد به ازای هر متغیر")
    parser.add_argument(
        "--start-time",
        type=lambda s: datetime.fromisoformat(s),
        default=datetime.now().replace(microsecond=0),
        help="زمان شروع به فرمت ISO (پیش‌فرض: اکنون)",
    )
    parser.add_argument("--seed", type=int, default=None, help="seed برای تولید داده قابل‌بازتولید")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "petrochemical_sensor_data_10k.csv",
        help="مسیر فایل CSV خروجی",
    )
    args = parser.parse_args()

    df = generate_dataset(args.num_records, args.start_time, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

    print(f"داده‌های سنتتیک با موفقیت در فایل '{args.output}' ذخیره شدند.")
    print(f"تعداد رکوردها: {len(df):,} - تعداد متغیرها: {len(df.columns)}")
    print("\nنمونه داده‌های تولید شده:")
    print(df.head())
    print("\nآمار توصیفی داده‌ها:")
    print(df.describe())


if __name__ == "__main__":
    main()
