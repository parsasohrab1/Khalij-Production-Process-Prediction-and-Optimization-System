"""Automatic generation of the energy optimization report at the end of each shift (R-GEN-04).

Shifts (Asia/Tehran):
  morning : 08:00 → 16:00
  evening : 16:00 → 00:00
  night   : 00:00 → 08:00

At the end of each shift, the average efficiency and estimated energy savings are computed from the applied
optimization recommendations and stored in the shift_reports table.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

try:
    from zoneinfo import ZoneInfo

    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # noqa: BLE001 - on Windows without tzdata a fixed offset is used
    TEHRAN = timezone(timedelta(hours=3, minutes=30))

logger = logging.getLogger(__name__)

# (shift name, local start hour, duration in hours)
_SHIFTS = (
    ("morning", 8, 8),
    ("evening", 16, 8),
    ("night", 0, 8),
)


def _pg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg2", "postgresql")


def resolve_shift_window(now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """Returns the current shift based on Tehran time: (name, UTC start, UTC end)."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(TEHRAN)
    hour = local_now.hour
    if 8 <= hour < 16:
        name, start_h, duration = "morning", 8, 8
    elif 16 <= hour < 24:
        name, start_h, duration = "evening", 16, 8
    else:
        name, start_h, duration = "night", 0, 8

    start_local = local_now.replace(hour=start_h, minute=0, second=0, microsecond=0)
    if name == "night" and hour >= 0 and hour < 8:
        # the night shift started at midnight today
        pass
    end_local = start_local + timedelta(hours=duration)
    return name, start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def previous_shift_window(now: datetime | None = None) -> tuple[str, datetime, datetime]:
    """Window of the previous shift (for generating the report at the start of a new shift)."""
    local_now = (now or datetime.now(timezone.utc)).astimezone(TEHRAN)
    name, start_utc, _ = resolve_shift_window(local_now)
    # one hour before the start of the current shift → inside the previous shift
    prev_point = start_utc - timedelta(minutes=1)
    return resolve_shift_window(prev_point)


class ShiftReportGenerator:
    def __init__(self, dsn: str):
        self._dsn = _pg_dsn(dsn)

    def _connect(self):
        return psycopg2.connect(self._dsn)

    def generate(self, unit_id: int = 1, shift_name: str | None = None,
                 shift_start: datetime | None = None, shift_end: datetime | None = None) -> dict | None:
        """Generate and store the shift report. If no range is given, the previous shift is computed."""
        if shift_name is None or shift_start is None or shift_end is None:
            shift_name, shift_start, shift_end = previous_shift_window()

        # avoid duplicate reports
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM shift_reports
                WHERE unit_id = %s AND shift = %s AND shift_start = %s
                """,
                (unit_id, shift_name, shift_start),
            )
            if cur.fetchone():
                logger.info("Shift report %s for unit %s was already generated.", shift_name, unit_id)
                return None

            cur.execute(
                """
                SELECT
                    COALESCE(AVG(expected_efficiency_gain), 0) AS avg_gain,
                    COUNT(*) AS rec_count,
                    COALESCE(SUM(expected_efficiency_gain), 0) AS total_gain
                FROM optimization_recommendations
                WHERE unit_id = %s
                  AND created_at >= %s AND created_at < %s
                """,
                (unit_id, shift_start, shift_end),
            )
            avg_gain, rec_count, total_gain = cur.fetchone()

            # base efficiency 60% + average improvement of recommendations; approximate energy saved
            avg_efficiency = round(60.0 + float(avg_gain), 2)
            # assumption: each 1% efficiency improvement ≈ 5 kWh saved in an 8-hour shift
            energy_saved_kwh = round(float(total_gain) * 5.0, 2)
            summary = (
                f"Shift {shift_name}: {rec_count} optimization recommendations recorded; "
                f"average efficiency improvement {float(avg_gain):.2f}%; "
                f"estimated energy savings {energy_saved_kwh} kWh."
            )

            cur.execute(
                """
                INSERT INTO shift_reports
                    (unit_id, shift, shift_start, shift_end, avg_efficiency,
                     energy_saved_kwh, recommendation_summary)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, generated_at
                """,
                (unit_id, shift_name, shift_start, shift_end, avg_efficiency, energy_saved_kwh, summary),
            )
            report_id, generated_at = cur.fetchone()
            conn.commit()

        report = {
            "id": report_id,
            "unit_id": unit_id,
            "shift": shift_name,
            "shift_start": shift_start.isoformat(),
            "shift_end": shift_end.isoformat(),
            "avg_efficiency": avg_efficiency,
            "energy_saved_kwh": energy_saved_kwh,
            "recommendation_summary": summary,
            "generated_at": generated_at.isoformat() if generated_at else None,
        }
        logger.info("Shift report generated: %s", summary)
        return report

    def list_recent(self, limit: int = 20) -> list[dict]:
        query = """
            SELECT id, unit_id, shift, shift_start, shift_end, avg_efficiency,
                   energy_saved_kwh, recommendation_summary, generated_at
            FROM shift_reports
            ORDER BY generated_at DESC
            LIMIT %s
        """
        try:
            with self._connect() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, (limit,))
                rows = cur.fetchall()
                return [
                    {
                        **dict(row),
                        "shift_start": row["shift_start"].isoformat() if row["shift_start"] else None,
                        "shift_end": row["shift_end"].isoformat() if row["shift_end"] else None,
                        "generated_at": row["generated_at"].isoformat() if row["generated_at"] else None,
                    }
                    for row in rows
                ]
        except Exception:  # noqa: BLE001
            logger.exception("Reading shift reports failed.")
            return []
