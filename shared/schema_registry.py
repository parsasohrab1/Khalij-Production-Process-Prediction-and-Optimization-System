"""Schema Registry سبک مبتنی بر Pydantic برای پیام‌های Kafka (فاز ۲).

به‌جای وابستگی سنگین به Confluent Schema Registry / Avro، نسخه‌بندی schema
با مدل‌های Pydantic انجام می‌شود. هر پیام هنگام ارسال/دریافت اعتبارسنجی می‌شود
تا ناسازگاری بین میکروسرویس‌ها زود تشخیص داده شود.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Type

from pydantic import BaseModel, ValidationError

from shared.schemas import Alert, PredictionResult, ProcessedReading, SensorReading

logger = logging.getLogger(__name__)


class SchemaName(str, Enum):
    RAW_SENSOR = "raw-sensor-data"
    PROCESSED_SENSOR = "processed-sensor-data"
    PREDICTION = "process-predictions"
    ALERT = "process-alerts"


# نسخه فعلی هر schema — در صورت شکستن سازگاری، نسخه را افزایش دهید
SCHEMA_VERSIONS: dict[SchemaName, str] = {
    SchemaName.RAW_SENSOR: "1.0.0",
    SchemaName.PROCESSED_SENSOR: "1.0.0",
    SchemaName.PREDICTION: "1.0.0",
    SchemaName.ALERT: "1.0.0",
}

_SCHEMA_MODELS: dict[SchemaName, Type[BaseModel]] = {
    SchemaName.RAW_SENSOR: SensorReading,
    SchemaName.PROCESSED_SENSOR: ProcessedReading,
    SchemaName.PREDICTION: PredictionResult,
    SchemaName.ALERT: Alert,
}


class SchemaValidationError(ValueError):
    """پیام با schema ثبت‌شده سازگار نیست."""

    def __init__(self, schema_name: SchemaName, errors: list[dict[str, Any]], payload: dict | None = None):
        self.schema_name = schema_name
        self.errors = errors
        self.payload = payload
        super().__init__(f"اعتبارسنجی schema '{schema_name.value}' ناموفق: {errors}")


def get_schema_version(schema_name: SchemaName | str) -> str:
    name = SchemaName(schema_name) if isinstance(schema_name, str) else schema_name
    return SCHEMA_VERSIONS[name]


def stamp_schema_metadata(payload: dict, schema_name: SchemaName | str) -> dict:
    """افزودن فیلدهای _schema و _schema_version به پیام قبل از ارسال."""
    name = SchemaName(schema_name) if isinstance(schema_name, str) else schema_name
    stamped = dict(payload)
    stamped["_schema"] = name.value
    stamped["_schema_version"] = SCHEMA_VERSIONS[name]
    return stamped


def validate_message(payload: dict, schema_name: SchemaName | str) -> BaseModel:
    """اعتبارسنجی payload در برابر مدل Pydantic مربوطه.

    Raises:
        SchemaValidationError: در صورت شکست اعتبارسنجی
    """
    name = SchemaName(schema_name) if isinstance(schema_name, str) else schema_name
    model = _SCHEMA_MODELS[name]

    # متادیتای schema را قبل از اعتبارسنجی مدل حذف می‌کنیم
    clean = {k: v for k, v in payload.items() if not k.startswith("_")}

    # برای SensorReading، فیلدهای اختیاری خارج از مدل (مثل efficiency) نادیده گرفته می‌شوند
    try:
        return model.model_validate(clean)
    except ValidationError as exc:
        raise SchemaValidationError(name, exc.errors(), payload=payload) from exc


def try_validate(payload: dict, schema_name: SchemaName | str) -> tuple[BaseModel | None, SchemaValidationError | None]:
    """نسخه بدون exception برای استفاده در حلقه مصرف‌کننده."""
    try:
        return validate_message(payload, schema_name), None
    except SchemaValidationError as exc:
        return None, exc
