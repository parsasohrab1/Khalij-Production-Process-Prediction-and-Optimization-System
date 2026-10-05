"""Data normalization with Min-Max or StandardScaler for model input (FR-PRE-03)."""
from __future__ import annotations

# allowed physical range of each sensor per FR-DATA-02 and the SRS document
SENSOR_RANGES: dict[str, tuple[float, float]] = {
    "reactor_temp_c": (150.0, 350.0),
    "reactor_pressure_bar": (10.0, 40.0),
    "feed_flow_m3h": (100.0, 500.0),
    "tank_level_percent": (20.0, 85.0),
    "ethylene_conc_percent": (12.0, 25.0),
    "compressor_rpm": (1200.0, 1800.0),
}


def min_max_normalize(field: str, value: float) -> float:
    """Min-Max normalization based on the sensor's allowed physical range, output in [0, 1]."""
    low, high = SENSOR_RANGES.get(field, (0.0, 1.0))
    if high == low:
        return 0.0
    normalized = (value - low) / (high - low)
    return max(0.0, min(1.0, normalized))


def standard_normalize(value: float, mean: float, std: float) -> float:
    """StandardScaler normalization: (x - mean) / std."""
    if std == 0:
        return 0.0
    return (value - mean) / std


def normalize_reading(reading: dict) -> dict:
    """Output: mapping of each sensor field to its Min-Max normalized value between 0 and 1."""
    return {field: min_max_normalize(field, reading[field]) for field in SENSOR_RANGES if field in reading}
