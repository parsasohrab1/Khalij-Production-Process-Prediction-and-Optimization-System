"""ردیابی توزیع‌شده با OpenTelemetry (فاز ۸).

اگر OTEL_EXPORTER_OTLP_ENDPOINT تنظیم نشده باشد، tracing غیرفعال می‌ماند.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def setup_tracing(service_name: str, app=None) -> bool:
    """راه‌اندازی OTLP tracing. True اگر فعال شد."""
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info("OTEL_EXPORTER_OTLP_ENDPOINT خالی است؛ tracing غیرفعال.")
        return False
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("بسته‌های OpenTelemetry نصب نیستند؛ tracing غیرفعال.")
        return False

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": "khalij-pos",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        }
    )
    provider = TracerProvider(resource=resource)
    # endpoint مثل http://tempo:4318  → مسیر /v1/traces
    traces_url = endpoint.rstrip("/")
    if not traces_url.endswith("/v1/traces"):
        traces_url = f"{traces_url}/v1/traces"
    exporter = OTLPSpanExporter(endpoint=traces_url)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor.instrument_app(app)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FastAPI instrumentation ناموفق: %s", exc)

    logger.info("OpenTelemetry tracing فعال شد → %s", traces_url)
    return True
