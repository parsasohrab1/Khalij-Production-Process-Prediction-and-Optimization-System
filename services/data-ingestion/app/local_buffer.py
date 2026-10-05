"""Local buffer for storing data when communication with Kafka is lost (FR-DATA-03).

Messages that fail to send are kept in a local SQLite file
and are resent in FIFO order as soon as the connection is restored.
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
        logger.warning("Message stored in the local buffer (no connection to Kafka).")

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
