"""پیکربندی یکسان لاگ برای همه سرویس‌ها (فاز ۸: JSON ساختاریافته)."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        for key in ("request_id", "trace_id", "span_id", "unit_id", "path", "method", "status"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(service_name: str, level: str = "INFO") -> None:
    """LOG_FORMAT=json|text — پیش‌فرض json در production، text در development."""
    fmt = os.getenv("LOG_FORMAT", "").strip().lower()
    env = os.getenv("ENVIRONMENT", "development").lower()
    use_json = fmt == "json" or (not fmt and env in {"production", "prod", "staging"})

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    if use_json:
        handler.setFormatter(JsonFormatter(service_name))
    else:
        handler.setFormatter(
            logging.Formatter(
                f"%(asctime)s | {service_name} | %(levelname)s | %(name)s | %(message)s"
            )
        )
    root.addHandler(handler)
