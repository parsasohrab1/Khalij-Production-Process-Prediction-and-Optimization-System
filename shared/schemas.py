"""مدل‌های داده مشترک (Pydantic) که بین سرویس‌ها از طریق Kafka/REST مبادله می‌شوند."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SensorReading(BaseModel):
    """یک رکورد خام دریافتی از OPC-UA/Modbus مطابق FR-DATA-02."""

    timestamp: datetime
    unit_id: int = 1
    reactor_temp_c: float
    reactor_pressure_bar: float
    feed_flow_m3h: float
    tank_level_percent: float
    ethylene_conc_percent: float
    compressor_rpm: float

    class Config:
        json_schema_extra = {
            "example": {
                "timestamp": "2026-07-22T08:00:00",
                "unit_id": 1,
                "reactor_temp_c": 250.12,
                "reactor_pressure_bar": 24.85,
                "feed_flow_m3h": 301.45,
                "tank_level_percent": 49.83,
                "ethylene_conc_percent": 18.12,
                "compressor_rpm": 1502,
            }
        }


class ProcessedReading(SensorReading):
    """خروجی ماژول پیش‌پردازش پس از حذف پرت، درون‌یابی و نرمال‌سازی (FR-PRE-01..03)."""

    is_outlier_corrected: bool = False
    is_interpolated: bool = False
    normalized: Optional[dict] = None


class PredictionResult(BaseModel):
    """خروجی ماژول پیش‌بینی برای دمای راکتور طی افق ۶۰ ثانیه (FR-ML-01)."""

    timestamp: datetime
    unit_id: int = 1
    horizon_seconds: int
    predicted_reactor_temp_c: float
    nominal_reactor_temp_c: float
    deviation_percent: float
    model_name: str
    model_version: Optional[str] = None
    mlflow_run_id: Optional[str] = None


class OptimizationRecommendation(BaseModel):
    """پیشنهاد سیستم توصیه‌گر برای دبی خوراک بهینه (FR-ML-03)."""

    timestamp: datetime
    unit_id: int = 1
    variable_name: str = "feed_flow_m3h"
    current_value: float
    recommended_value: float
    expected_efficiency_gain: float
    algorithm: str = "evolutionary"


class Alert(BaseModel):
    """هشدار صادر شده توسط ماژول پیش‌بینی یا مانیتورینگ (FR-ML-02, FR-ALERT-01/02)."""

    level: AlertLevel
    message: str
    sensor_tag: str
    predicted_value: Optional[float] = None
    nominal_value: Optional[float] = None
    deviation_percent: Optional[float] = None
    raised_at: datetime = Field(default_factory=datetime.utcnow)
    operator_id: Optional[int] = None
    acknowledged_at: Optional[datetime] = None
