"""بازخورد حلقه بسته: ثبت اعمال توصیه و تأثیر واقعی بر راندمان (فاز ۴)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)


def _pg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg2", "postgresql")


class OptimizationFeedbackStore:
    """ذخیره توصیه‌های چندمتغیره، اعمال توسط اپراتور، و بازخورد راندمان واقعی."""

    def __init__(self, dsn: str):
        self._dsn = _pg_dsn(dsn)

    def _connect(self):
        return psycopg2.connect(self._dsn)

    def ensure_schema(self) -> None:
        """افزودن ستون‌ها/جداول فاز ۴ در صورت نبود (migration سبک)."""
        ddl = """
        ALTER TABLE optimization_recommendations
            ADD COLUMN IF NOT EXISTS recommendation_json JSONB,
            ADD COLUMN IF NOT EXISTS expected_efficiency DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS actual_efficiency DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS efficiency_error DOUBLE PRECISION,
            ADD COLUMN IF NOT EXISTS feedback_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS whatif_snapshot JSONB;

        CREATE TABLE IF NOT EXISTS optimization_feedback_events (
            id                  BIGSERIAL PRIMARY KEY,
            recommendation_id   BIGINT REFERENCES optimization_recommendations(id) ON DELETE CASCADE,
            unit_id             INTEGER,
            event_type          VARCHAR(32) NOT NULL,  -- applied | feedback | rejected
            payload             JSONB,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            operator_id         INTEGER REFERENCES operators(id)
        );
        """
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(ddl)
                conn.commit()
        except Exception:  # noqa: BLE001
            logger.exception("migration فاز ۴ برای optimization_recommendations ناموفق بود.")

    def insert_recommendation(self, unit_id: int, recommendation: dict, model_run_id: str | None = None) -> int | None:
        query = """
            INSERT INTO optimization_recommendations
                (unit_id, variable_name, current_value, recommended_value,
                 expected_efficiency_gain, model_run_id, recommendation_json, expected_efficiency)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING id
        """
        expected_eff = recommendation.get("recommended", {}).get("estimated_efficiency")
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    query,
                    (
                        unit_id,
                        recommendation.get("variable_name", "feed_flow_m3h,pressure_bar"),
                        recommendation.get("current_value"),
                        recommendation.get("recommended_value"),
                        recommendation.get("expected_efficiency_gain"),
                        model_run_id,
                        json.dumps(recommendation, default=str),
                        expected_eff,
                    ),
                )
                row = cur.fetchone()
                conn.commit()
                return row[0] if row else None
        except Exception:  # noqa: BLE001
            logger.exception("ثبت توصیه چندمتغیره ناموفق بود.")
            return None

    def apply_recommendation(self, recommendation_id: int, operator_id: int, whatif_snapshot: dict | None = None) -> bool:
        query = """
            UPDATE optimization_recommendations
            SET applied = TRUE,
                applied_by = %s,
                whatif_snapshot = COALESCE(%s::jsonb, whatif_snapshot)
            WHERE id = %s AND applied = FALSE
            RETURNING id
        """
        try:
            with self._connect() as conn, conn.cursor() as cur:
                cur.execute(
                    query,
                    (operator_id, json.dumps(whatif_snapshot, default=str) if whatif_snapshot else None, recommendation_id),
                )
                row = cur.fetchone()
                if not row:
                    return False
                cur.execute(
                    """
                    INSERT INTO optimization_feedback_events
                        (recommendation_id, unit_id, event_type, payload, operator_id)
                    SELECT id, unit_id, 'applied', recommendation_json, %s
                    FROM optimization_recommendations WHERE id = %s
                    """,
                    (operator_id, recommendation_id),
                )
                conn.commit()
                return True
        except Exception:  # noqa: BLE001
            logger.exception("اعمال توصیه ناموفق بود.")
            return False

    def record_feedback(self, recommendation_id: int, actual_efficiency: float, operator_id: int | None = None) -> dict | None:
        """ثبت راندمان واقعی پس از اعمال و محاسبه خطای پیش‌بینی."""
        query = """
            UPDATE optimization_recommendations
            SET actual_efficiency = %s,
                efficiency_error = %s - COALESCE(expected_efficiency, 0),
                feedback_at = %s
            WHERE id = %s AND applied = TRUE
            RETURNING id, expected_efficiency, actual_efficiency, efficiency_error, expected_efficiency_gain, unit_id
        """
        now = datetime.now(timezone.utc)
        try:
            with self._connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                # ابتدا expected را بخوانیم تا error دقیق محاسبه شود
                cur.execute(
                    "SELECT expected_efficiency FROM optimization_recommendations WHERE id = %s",
                    (recommendation_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                expected = row["expected_efficiency"]
                cur.execute(query, (actual_efficiency, actual_efficiency, now, recommendation_id))
                updated = cur.fetchone()
                if not updated:
                    return None
                cur.execute(
                    """
                    INSERT INTO optimization_feedback_events
                        (recommendation_id, unit_id, event_type, payload, operator_id)
                    VALUES (%s, %s, 'feedback', %s::jsonb, %s)
                    """,
                    (
                        recommendation_id,
                        updated["unit_id"],
                        json.dumps(
                            {
                                "actual_efficiency": actual_efficiency,
                                "expected_efficiency": expected,
                                "efficiency_error": updated["efficiency_error"],
                            }
                        ),
                        operator_id,
                    ),
                )
                conn.commit()
                return {
                    "recommendation_id": updated["id"],
                    "expected_efficiency": updated["expected_efficiency"],
                    "actual_efficiency": updated["actual_efficiency"],
                    "efficiency_error": updated["efficiency_error"],
                    "expected_efficiency_gain": updated["expected_efficiency_gain"],
                }
        except Exception:  # noqa: BLE001
            logger.exception("ثبت بازخورد راندمان ناموفق بود.")
            return None

    def feedback_summary(self, limit: int = 50) -> dict:
        query = """
            SELECT
                COUNT(*) FILTER (WHERE applied) AS applied_count,
                COUNT(*) FILTER (WHERE actual_efficiency IS NOT NULL) AS feedback_count,
                AVG(efficiency_error) FILTER (WHERE efficiency_error IS NOT NULL) AS mean_error,
                AVG(expected_efficiency_gain) FILTER (WHERE applied) AS mean_expected_gain
            FROM optimization_recommendations
        """
        recent_q = """
            SELECT id, unit_id, expected_efficiency, actual_efficiency, efficiency_error,
                   expected_efficiency_gain, applied, created_at, feedback_at
            FROM optimization_recommendations
            WHERE actual_efficiency IS NOT NULL
            ORDER BY feedback_at DESC NULLS LAST
            LIMIT %s
        """
        try:
            with self._connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query)
                summary = dict(cur.fetchone() or {})
                cur.execute(recent_q, (limit,))
                recent = []
                for row in cur.fetchall():
                    item = dict(row)
                    for k in ("created_at", "feedback_at"):
                        if item.get(k):
                            item[k] = item[k].isoformat()
                    recent.append(item)
                return {"summary": summary, "recent_feedback": recent}
        except Exception:  # noqa: BLE001
            logger.exception("خوانش خلاصه بازخورد ناموفق بود.")
            return {"summary": {}, "recent_feedback": []}
