"""سرویس گزارش و هشدار (Alerting) - FR-ALERT-01, FR-ALERT-02, R-GEN-04.

مصرف هشدارهای صادرشده توسط سرویس پیش‌بینی از Kafka و توزیع آن‌ها از طریق
تلگرام، ایمیل و کش Redis (برای نمایش روی صفحه کنترل اتاق مرکزی)، همراه با
ثبت دائمی در PostgreSQL و تولید خودکار گزارش بهینه‌سازی انرژی پایان شیفت.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import redis
from confluent_kafka import Consumer, KafkaError
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from shared.health import install_health_probes
from shared.logging_config import configure_logging
from shared.metrics import inc_counter, install_prometheus_metrics
from shared.security import install_internal_api_key_middleware
from shared.settings import get_settings
from shared.tracing import setup_tracing

from .email_notifier import EmailNotifier
from .postgres_logger import AlertRepository
from .report_export import export_excel, export_pdf, fetch_shift_reports
from .shift_report import ShiftReportGenerator, resolve_shift_window
from .telegram_notifier import TelegramNotifier

settings = get_settings()
configure_logging("alerting", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Alerting Service", version="8.0.0")
install_internal_api_key_middleware(app)
install_prometheus_metrics(app, service_name="alerting")
setup_tracing("alerting", app)

_CONTROL_ROOM_CACHE_KEY = "control_room:recent_alerts"
_CONTROL_ROOM_CACHE_SIZE = 200
_SHIFT_CHECK_INTERVAL_S = 60  # هر دقیقه بررسی پایان شیفت

_stats = {
    "alerts_received": 0,
    "telegram_sent": 0,
    "email_sent": 0,
    "shift_reports_generated": 0,
}


class AcknowledgeRequest(BaseModel):
    operator_id: int


class AlertingWorker:
    def __init__(self) -> None:
        self._consumer = Consumer(
            {
                "bootstrap.servers": settings.kafka_bootstrap_servers,
                "group.id": f"{settings.kafka_consumer_group}-alerting",
                "auto.offset.reset": "latest",
                "enable.auto.commit": True,
            }
        )
        self._consumer.subscribe([settings.kafka_topic_alerts])
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        self._telegram = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
        self._email = EmailNotifier(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_address=settings.smtp_from_address,
            to_addresses=settings.smtp_to_addresses,
        )
        self._repository = AlertRepository(settings.postgres_dsn)
        self._shift_reports = ShiftReportGenerator(settings.postgres_dsn)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._shift_thread = threading.Thread(target=self._shift_loop, daemon=True)
        self._last_shift_checked: str | None = None

    def start(self) -> None:
        self._thread.start()
        self._shift_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._consumer.close()

    def _shift_loop(self) -> None:
        """در ابتدای هر شیفت جدید، گزارش شیفت قبلی را تولید می‌کند (R-GEN-04)."""
        logger.info("زمان‌بند گزارش شیفت شروع به کار کرد.")
        while not self._stop.is_set():
            try:
                current_shift, _, _ = resolve_shift_window()
                if self._last_shift_checked is not None and self._last_shift_checked != current_shift:
                    report = self._shift_reports.generate(unit_id=1)
                    if report:
                        _stats["shift_reports_generated"] += 1
                self._last_shift_checked = current_shift
            except Exception:  # noqa: BLE001
                logger.exception("خطا در تولید گزارش شیفت.")
            time.sleep(_SHIFT_CHECK_INTERVAL_S)

    def _run(self) -> None:
        logger.info("مصرف‌کننده هشدار شروع به کار کرد.")
        while not self._stop.is_set():
            msg = self._consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    continue
                logger.error("خطای Kafka: %s", msg.error())
                continue
            try:
                alert = json.loads(msg.value().decode("utf-8"))
                self._handle_alert(alert)
            except Exception:  # noqa: BLE001
                logger.exception("پردازش هشدار ناموفق بود.")

    def _handle_alert(self, alert: dict) -> None:
        _stats["alerts_received"] += 1
        inc_counter(
            "khalij_alerts_total",
            service="alerting",
            labels={"level": str(alert.get("level", "info"))},
        )
        message = (
            f"[{alert.get('level', 'info').upper()}] {alert.get('message')} "
            f"(سنسور: {alert.get('sensor_tag')})"
        )

        telegram_sent = self._telegram.send(message)
        email_sent = self._email.send(subject=f"هشدار {alert.get('level', 'info')} - Khalij POS", message=message)
        _stats["telegram_sent"] += int(telegram_sent)
        _stats["email_sent"] += int(email_sent)

        self._repository.insert_alert(alert, telegram_sent, email_sent)

        # نمایش روی صفحه کنترل اتاق مرکزی: کش لیستی در Redis که داشبورد آن را می‌خواند
        try:
            self._redis.lpush(_CONTROL_ROOM_CACHE_KEY, json.dumps(alert, default=str))
            self._redis.ltrim(_CONTROL_ROOM_CACHE_KEY, 0, _CONTROL_ROOM_CACHE_SIZE - 1)
        except Exception:  # noqa: BLE001
            logger.debug("به‌روزرسانی کش صفحه کنترل مرکزی ناموفق بود.")

        logger.info("هشدار پردازش شد: telegram=%s, email=%s", telegram_sent, email_sent)


_worker: AlertingWorker | None = None

install_health_probes(
    app,
    service_name="alerting",
    ready_check=lambda: _worker is not None,
)


@app.on_event("startup")
async def startup_event() -> None:
    global _worker
    _worker = AlertingWorker()
    _worker.start()
    logger.info("سرویس Alerting راه‌اندازی شد.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _worker:
        _worker.stop()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", **_stats}


@app.get("/alerts/recent")
async def recent_alerts(limit: int = 50) -> list[dict]:
    return _worker._repository.fetch_recent(limit) if _worker else []


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(alert_id: int, body: AcknowledgeRequest) -> dict:
    if not _worker:
        raise HTTPException(status_code=503, detail="سرویس هنوز آماده نیست.")
    ok = _worker._repository.acknowledge_alert(alert_id, body.operator_id)
    if not ok:
        raise HTTPException(status_code=404, detail="هشدار یافت نشد.")
    return {"acknowledged": True, "alert_id": alert_id, "operator_id": body.operator_id}


@app.post("/reports/shift/generate")
async def generate_shift_report(unit_id: int = 1) -> dict:
    """تولید دستی گزارش شیفت قبلی (R-GEN-04) — برای تست یا اجرای اضطراری."""
    if not _worker:
        raise HTTPException(status_code=503, detail="سرویس هنوز آماده نیست.")
    report = _worker._shift_reports.generate(unit_id=unit_id)
    if report is None:
        return {"status": "already_exists_or_empty", "unit_id": unit_id}
    _stats["shift_reports_generated"] += 1
    return report


@app.get("/reports/shift/recent")
async def recent_shift_reports(limit: int = 20) -> list[dict]:
    if not _worker:
        return []
    return _worker._shift_reports.list_recent(limit)


@app.get("/reports/shift/export")
async def export_shift_reports(format: str = "xlsx", limit: int = 50) -> Response:
    """خروجی PDF یا Excel گزارش‌های شیفت (فاز ۵ / R-GEN-04)."""
    fmt = format.lower().strip()
    if fmt not in {"pdf", "xlsx", "excel"}:
        raise HTTPException(status_code=400, detail="فرمت باید pdf یا xlsx باشد.")
    if fmt == "excel":
        fmt = "xlsx"
    reports = fetch_shift_reports(settings.postgres_dsn, limit=limit)
    if fmt == "pdf":
        content = export_pdf(reports)
        media = "application/pdf"
        filename = "shift_reports.pdf"
    else:
        content = export_excel(reports)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "shift_reports.xlsx"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
