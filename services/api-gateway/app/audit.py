"""ثبت وقایع امنیتی و عملیاتی (Audit Trail) — فاز ۶."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import psycopg2

from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _pg_dsn() -> str:
    return settings.postgres_dsn.replace("postgresql+psycopg2", "postgresql")


ENSURE_SQL = """
CREATE TABLE IF NOT EXISTS audit_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,
    actor_code      VARCHAR(32),
    actor_role      VARCHAR(32),
    resource        VARCHAR(128),
    action          VARCHAR(64) NOT NULL,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    ip_address      VARCHAR(64),
    user_agent      TEXT,
    details         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events (actor_code);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type);
"""


class AuditLogger:
    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _pg_dsn()
        self._ready = False

    def ensure_schema(self) -> None:
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(ENSURE_SQL)
                conn.commit()
            self._ready = True
        except Exception:  # noqa: BLE001
            logger.exception("ایجاد جدول audit_events ناموفق بود.")

    def log(
        self,
        *,
        event_type: str,
        action: str,
        success: bool = True,
        actor_code: str | None = None,
        actor_role: str | None = None,
        resource: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        details: dict | None = None,
    ) -> None:
        if not self._ready:
            self.ensure_schema()
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO audit_events
                        (event_type, actor_code, actor_role, resource, action, success,
                         ip_address, user_agent, details, created_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)
                    """,
                    (
                        event_type,
                        actor_code,
                        actor_role,
                        resource,
                        action,
                        success,
                        ip_address,
                        user_agent,
                        json.dumps(details or {}, default=str),
                        datetime.now(timezone.utc),
                    ),
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            logger.debug("ثبت audit ناموفق بود.", exc_info=True)

    def list_recent(self, limit: int = 50) -> list[dict]:
        if not self._ready:
            self.ensure_schema()
        try:
            with psycopg2.connect(self._dsn) as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, event_type, actor_code, actor_role, resource, action,
                           success, ip_address, details, created_at
                    FROM audit_events
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                cols = [d[0] for d in cur.description]
                rows = []
                for row in cur.fetchall():
                    item = dict(zip(cols, row))
                    if item.get("created_at"):
                        item["created_at"] = item["created_at"].isoformat()
                    rows.append(item)
                return rows
        except Exception:  # noqa: BLE001
            logger.exception("خوانش audit ناموفق بود.")
            return []


_audit = AuditLogger()


def get_audit() -> AuditLogger:
    return _audit
