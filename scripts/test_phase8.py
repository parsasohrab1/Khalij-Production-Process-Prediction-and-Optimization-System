"""تست‌های واحد فاز ۸: مشاهده‌پذیری (متریک، SLO، لاگ JSON، tracing stub).

اجرا:
    python scripts/test_phase8.py
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_slo_budget() -> None:
    from shared.slo import NFR_PER_02_MONTHLY, NFR_PER_02_WEEKLY, availability_from_checks

    weekly = NFR_PER_02_WEEKLY.as_dict(0)
    assert weekly["slo_met"] is True
    # بیش از بودجه هفتگی (~60.48 ثانیه)
    burned = NFR_PER_02_WEEKLY.as_dict(120)
    assert burned["slo_met"] is False
    assert burned["burn_ratio"] > 1
    assert abs(NFR_PER_02_WEEKLY.error_budget_seconds - (1 - 0.9999) * 7 * 86400) < 1e-6
    assert availability_from_checks(9999, 10000) == 0.9999
    monthly = NFR_PER_02_MONTHLY.as_dict(0)
    assert monthly["objective_percent"] == 99.99
    print(f"[OK] SLO weekly budget={weekly['error_budget_seconds']:.1f}s")


def test_json_logging() -> None:
    import os

    os.environ["LOG_FORMAT"] = "json"
    os.environ["ENVIRONMENT"] = "production"
    from shared.logging_config import configure_logging

    configure_logging("test-svc", "INFO")
    logger = logging.getLogger("phase8.test")
    # capture one record via handler
    records: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record):
            records.append(self.format(record))

    h = Capture()
    from shared.logging_config import JsonFormatter

    h.setFormatter(JsonFormatter("test-svc"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
    logger.info("hello-obs")
    assert records
    payload = json.loads(records[0])
    assert payload["service"] == "test-svc"
    assert payload["message"] == "hello-obs"
    assert payload["level"] == "INFO"
    print("[OK] JSON logging")


def test_prometheus_metrics_endpoint() -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from shared.metrics import install_prometheus_metrics, prometheus_available

    assert prometheus_available()
    app = FastAPI()
    install_prometheus_metrics(app, service_name="unit-test")

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    client = TestClient(app)
    assert client.get("/ping").status_code == 200
    res = client.get("/metrics")
    assert res.status_code == 200
    body = res.text
    assert "khalij_http_requests_total" in body
    assert "khalij_http_request_duration_seconds" in body
    print("[OK] prometheus /metrics")


def test_tracing_disabled_without_endpoint() -> None:
    import os

    os.environ.pop("OTEL_EXPORTER_OTLP_ENDPOINT", None)
    from shared.tracing import setup_tracing

    assert setup_tracing("demo") is False
    print("[OK] tracing disabled by default")


def test_observability_artifacts() -> None:
    base = ROOT / "infra" / "observability"
    assert (base / "prometheus" / "prometheus.yml").exists()
    assert (base / "prometheus" / "alerts.yml").exists()
    assert (base / "grafana" / "dashboards" / "khalij-pos-overview.json").exists()
    assert (base / "loki" / "loki-config.yml").exists()
    assert (base / "tempo" / "tempo.yaml").exists()
    assert (ROOT / "docker-compose.observability.yml").exists()
    alerts = (base / "prometheus" / "alerts.yml").read_text(encoding="utf-8")
    assert "NFR-PER-02" in alerts
    assert "ServiceDown" in alerts
    print("[OK] observability infra files")


if __name__ == "__main__":
    test_slo_budget()
    test_json_logging()
    test_prometheus_metrics_endpoint()
    test_tracing_disabled_without_endpoint()
    test_observability_artifacts()
    print("\nفاز ۸: همه تست‌های واحد پاس شدند.")
