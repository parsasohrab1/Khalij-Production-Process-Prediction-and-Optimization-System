"""سرویس گزارش و هشدار (Alerting) - FR-ALERT-01, FR-ALERT-02.

مصرف هشدارهای صادرشده توسط سرویس پیش‌بینی از Kafka و توزیع آن‌ها از طریق
تلگرام، ایمیل و کش Redis (برای نمایش روی صفحه کنترل اتاق مرکزی)، همراه با
ثبت دائمی در PostgreSQL.
"""
from __future__ import annotations

import json
import logging
import threading

import redis
from confluent_kafka import Consumer, KafkaError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shared.logging_config import configure_logging
from shared.settings import get_settings

from .email_notifier import EmailNotifier
from .postgres_logger import AlertRepository
from .telegram_notifier import TelegramNotifier

settings = get_settings()
configure_logging("alerting", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - Alerting Service", version="1.0.0")

_CONTROL_ROOM_CACHE_KEY = "control_room:recent_alerts"
_CONTROL_ROOM_CACHE_SIZE = 200

_stats = {"alerts_received": 0, "telegram_sent": 0, "email_sent": 0}


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
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._consumer.close()

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
