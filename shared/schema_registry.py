"""Lightweight Pydantic-based Schema Registry for Kafka messages (phase 2).

Instead of a heavy dependency on the Confluent Schema Registry / Avro, schema versioning
is done with Pydantic models. Each message is validated on send/receive
so that incompatibilities between microservices are detected early.
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


# current version of each schema — increase the version if compatibility is broken
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
    """The message is not compatible with the registered schema."""

    def __init__(self, schema_name: SchemaName, errors: list[dict[str, Any]], payload: dict | None = None):
        self.schema_name = schema_name
        self.errors = errors
        self.payload = payload
        super().__init__(f"Validation of schema '{schema_name.value}' failed: {errors}")


def get_schema_version(schema_name: SchemaName | str) -> str:
    name = SchemaName(schema_name) if isinstance(schema_name, str) else schema_name
    return SCHEMA_VERSIONS[name]


def stamp_schema_metadata(payload: dict, schema_name: SchemaName | str) -> dict:
    """Add the _schema and _schema_version fields to the message before sending."""
    name = SchemaName(schema_name) if isinstance(schema_name, str) else schema_name
    stamped = dict(payload)
    stamped["_schema"] = name.value
    stamped["_schema_version"] = SCHEMA_VERSIONS[name]
    return stamped


def validate_message(payload: dict, schema_name: SchemaName | str) -> BaseModel:
    """Validate the payload against the corresponding Pydantic model.

    Raises:
        SchemaValidationError: if validation fails
    """
    name = SchemaName(schema_name) if isinstance(schema_name, str) else schema_name
    model = _SCHEMA_MODELS[name]

    # we remove the schema metadata before model validation
    clean = {k: v for k, v in payload.items() if not k.startswith("_")}

    # for SensorReading, optional fields outside the model (such as efficiency) are ignored
    try:
        return model.model_validate(clean)
    except ValidationError as exc:
        raise SchemaValidationError(name, exc.errors(), payload=payload) from exc


def try_validate(payload: dict, schema_name: SchemaName | str) -> tuple[BaseModel | None, SchemaValidationError | None]:
    """Exception-free version for use in the consumer loop."""
    try:
        return validate_message(payload, schema_name), None
    except SchemaValidationError as exc:
        return None, exc
