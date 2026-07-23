"""بافر محلی برای ذخیره داده هنگام قطع ارتباط با Kafka (FR-DATA-03).

پیام‌هایی که ارسال آن‌ها ناموفق باشد در یک فایل SQLite محلی نگهداری می‌شوند
و به محض اتصال مجدد، به‌صورت FIFO دوباره ارسال می‌شوند.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalBuffer:
    def __init__(self, db_path: str = "/tmp/data_ingestion_buffer.sqlite3"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self._conn.commit()

    def push(self, topic: str, payload: dict) -> None:
        self._conn.execute(
            "INSERT INTO pending_messages (topic, payload) VALUES (?, ?)",
            (topic, json.dumps(payload)),
        )
        self._conn.commit()
        logger.warning("پیام در بافر محلی ذخیره شد (ارتباط با Kafka برقرار نیست).")

    def drain(self, max_batch: int = 500):
        cursor = self._conn.execute(
            "SELECT id, topic, payload FROM pending_messages ORDER BY id ASC LIMIT ?",
            (max_batch,),
        )
        rows = cursor.fetchall()
        for row_id, topic, payload in rows:
            yield row_id, topic, json.loads(payload)

    def remove(self, row_id: int) -> None:
        self._conn.execute("DELETE FROM pending_messages WHERE id = ?", (row_id,))
        self._conn.commit()

    def pending_count(self) -> int:
        cursor = self._conn.execute("SELECT COUNT(*) FROM pending_messages")
        return cursor.fetchone()[0]
