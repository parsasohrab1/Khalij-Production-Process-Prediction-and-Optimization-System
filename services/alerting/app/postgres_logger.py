"""ثبت لاگ کلیه هشدارها با زمان دقیق و شناسه اپراتور پاسخ‌دهنده (FR-ALERT-02).

متن هشدار با AES-256-GCM رمزنگاری می‌شود (NFR-SEC-02) پیش از ذخیره در PostgreSQL.
"""
from __future__ import annotations

import logging

import psycopg2
import psycopg2.extras

from shared.crypto import decrypt_at_rest, encrypt_at_rest

logger = logging.getLogger(__name__)


class AlertRepository:
    def __init__(self, dsn: str):
        # psycopg2 از پیشوند SQLAlchemy (postgresql+psycopg2) پشتیبانی نمی‌کند
        self._dsn = dsn.replace("postgresql+psycopg2", "postgresql")

    def _connect(self):
        return psycopg2.connect(self._dsn)

    def insert_alert(self, alert: dict, telegram_sent: bool, email_sent: bool) -> int | None:
        query = """
            INSERT INTO alerts (
                sensor_id, level, message, predicted_value, nominal_value,
                deviation_percent, channel_telegram_sent, channel_email_sent, raised_at
            )
            SELECT s.id, %(level)s, %(message)s, %(predicted_value)s, %(nominal_value)s,
                   %(deviation_percent)s, %(telegram_sent)s, %(email_sent)s, %(raised_at)s
            FROM sensors s WHERE s.tag = %(sensor_tag)s
            RETURNING id
        """
        params = {
            "level": alert["level"],
            "message": encrypt_at_rest(alert["message"]),
            "predicted_value": alert.get("predicted_value"),
            "nominal_value": alert.get("nominal_value"),
            "deviation_percent": alert.get("deviation_percent"),
            "telegram_sent": telegram_sent,
            "email_sent": email_sent,
            "raised_at": alert.get("raised_at"),
            "sensor_tag": alert.get("sensor_tag"),
        }
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(query, params)
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:  # noqa: BLE001
            logger.exception("ثبت هشدار در PostgreSQL ناموفق بود.")
            return None

    def acknowledge_alert(self, alert_id: int, operator_id: int) -> bool:
        query = """
            UPDATE alerts SET acknowledged_at = now(), acknowledged_by = %s WHERE id = %s
        """
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(query, (operator_id, alert_id))
                return cur.rowcount > 0
        except Exception:  # noqa: BLE001
            logger.exception("ثبت پاسخ اپراتور به هشدار ناموفق بود.")
            return False

    def fetch_recent(self, limit: int = 50) -> list[dict]:
        query = """
            SELECT a.id, s.tag AS sensor_tag, a.level, a.message, a.predicted_value,
                   a.nominal_value, a.deviation_percent, a.raised_at, a.acknowledged_at, a.acknowledged_by
            FROM alerts a
            LEFT JOIN sensors s ON s.id = a.sensor_id
            ORDER BY a.raised_at DESC
            LIMIT %s
        """
        try:
            with self._connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (limit,))
                rows = []
                for row in cur.fetchall():
                    item = dict(row)
                    try:
                        item["message"] = decrypt_at_rest(item["message"] or "")
                    except RuntimeError:
                        pass  # در صورت نبود کلید، مقدار رمزشده را همان‌طور برمی‌گرداند
                    rows.append(item)
                return rows
        except Exception:  # noqa: BLE001
            logger.exception("خوانش هشدارهای اخیر از PostgreSQL ناموفق بود.")
            return []
