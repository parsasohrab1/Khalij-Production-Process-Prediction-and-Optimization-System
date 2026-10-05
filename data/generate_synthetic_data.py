"""
Generation of synthetic (simulated) sensor data for a petrochemical production process.

This script generates 10,000 records for each of the 7 key variables at a rate of 1 record per second
(sinusoidal patterns + trend + Gaussian noise) and saves them in a CSV file.
This data is used for initial training of prediction models and testing the preprocessing pipeline.

Run:
    python data/generate_synthetic_data.py
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# On the Windows console (cp1256/cp1252) printing Persian text directly raises UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def generate_dataset(num_records: int, start_time: datetime, seed: int | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(seed)

    timestamps = [start_time + timedelta(seconds=i) for i in range(num_records)]
    t = np.linspace(0, 20 * np.pi, num_records)

    # 1. Reactor Temperature - range 150 to 350 degrees Celsius
    reactor_temp = 250 + 30 * np.sin(t * 0.5) + 0.01 * np.arange(num_records) + rng.normal(0, 2, num_records)
    reactor_temp = np.clip(reactor_temp, 150, 350)

    # 2. Reactor Pressure - range 10 to 40 bar
    pressure = 25 + 5 * np.sin(t * 0.3) + 0.005 * np.arange(num_records) + rng.normal(0, 0.8, num_records)
    pressure = np.clip(pressure, 10, 40)

    # 3. Feed Flow - range 100 to 500 cubic meters per hour
    feed_flow = 300 + 80 * np.sin(t * 0.2 + 1.2) + rng.normal(0, 5, num_records)
    feed_flow = np.clip(feed_flow, 100, 500)

    # 4. Tank Level - range 20 to 85 percent
    tank_level = 50 + 20 * np.sin(t * 0.15 + 2.5) + rng.normal(0, 1.5, num_records)
    tank_level = np.clip(tank_level, 20, 85)

    # 5. Output gas composition (Ethylene Concentration) - range 12 to 25 percent
    ethylene_conc = 18 + 3 * np.sin(t * 0.25 + 0.8) + 0.002 * np.arange(num_records) + rng.normal(0, 0.5, num_records)
    ethylene_conc = np.clip(ethylene_conc, 12, 25)

    # 6. Compressor RPM - range 1200 to 1800 revolutions per minute
    compressor_rpm = 1500 + 150 * np.sin(t * 0.1 + 3.0) + rng.normal(0, 10, num_records)
    compressor_rpm = np.clip(compressor_rpm, 1200, 1800)

    # 7. Production Efficiency - target variable, a function of temperature and pressure
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
    parser = argparse.ArgumentParser(description="Generate synthetic data for production process sensors")
    parser.add_argument("--num-records", type=int, default=10_000, help="number of records per variable")
    parser.add_argument(
        "--start-time",
        type=lambda s: datetime.fromisoformat(s),
        default=datetime.now().replace(microsecond=0),
        help="start time in ISO format (default: now)",
    )
    parser.add_argument("--seed", type=int, default=None, help="seed for reproducible data generation")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "petrochemical_sensor_data_10k.csv",
        help="path of the output CSV file",
    )
    args = parser.parse_args()

    df = generate_dataset(args.num_records, args.start_time, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False)

    print(f"Synthetic data was successfully saved to file '{args.output}'.")
    print(f"Number of records: {len(df):,} - number of variables: {len(df.columns)}")
    print("\nSample of generated data:")
    print(df.head())
    print("\nDescriptive statistics of the data:")
    print(df.describe())


if __name__ == "__main__":
    main()
