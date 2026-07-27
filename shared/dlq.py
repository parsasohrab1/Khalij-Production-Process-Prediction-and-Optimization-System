"""ارسال پیام‌های نامعتبر به Dead Letter Queue (فاز ۲).

هر پیام خراب همراه با دلیل خطا، موضوع مبدأ، و زمان رد شدن به topic مربوط به DLQ
ارسال می‌شود تا بدون مسدود کردن خط لوله اصلی قابل بررسی باشد.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from confluent_kafka import Producer

logger = logging.getLogger(__name__)


class DeadLetterPublisher:
    def __init__(self, bootstrap_servers: str, dlq_topic: str, client_id: str = "dlq-publisher"):
        self.dlq_topic = dlq_topic
        self._producer = Producer({"bootstrap.servers": bootstrap_servers, "client.id": client_id})

    def publish(
        self,
        *,
        original_topic: str,
        payload: Any,
        error: str,
        schema_name: str | None = None,
        extra: dict | None = None,
    ) -> None:
        envelope = {
            "original_topic": original_topic,
            "schema_name": schema_name,
            "error": error,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
            "payload": payload if isinstance(payload, (dict, list, str, int, float, bool, type(None))) else str(payload),
            "extra": extra or {},
        }
        try:
            self._producer.produce(
                self.dlq_topic,
                value=json.dumps(envelope, default=str).encode("utf-8"),
            )
            self._producer.poll(0)
            logger.warning("پیام به DLQ ارسال شد (%s): %s", self.dlq_topic, error)
        except BufferError:
            logger.error("صف DLQ پر است؛ پیام ردشده از دست رفت.")

    def flush(self, timeout: float = 5.0) -> None:
        self._producer.flush(timeout)
