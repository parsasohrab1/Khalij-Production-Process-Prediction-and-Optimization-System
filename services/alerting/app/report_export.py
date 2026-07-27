"""خروجی گزارش بهینه‌سازی انرژی پایان شیفت به PDF و Excel (فاز ۵ / R-GEN-04)."""
from __future__ import annotations

import io
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)


def _pg_dsn(dsn: str) -> str:
    return dsn.replace("postgresql+psycopg2", "postgresql")


def fetch_shift_reports(dsn: str, limit: int = 50) -> list[dict]:
    query = """
        SELECT id, unit_id, shift, shift_start, shift_end, avg_efficiency,
               energy_saved_kwh, recommendation_summary, generated_at
        FROM shift_reports
        ORDER BY generated_at DESC
        LIMIT %s
    """
    try:
        with psycopg2.connect(_pg_dsn(dsn)) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (limit,))
            rows = []
            for row in cur.fetchall():
                item = dict(row)
                for k in ("shift_start", "shift_end", "generated_at"):
                    if item.get(k):
                        item[k] = item[k].isoformat()
                rows.append(item)
            return rows
    except Exception:  # noqa: BLE001
        logger.exception("خوانش گزارش شیفت ناموفق بود.")
        return []


def fetch_shift_report(dsn: str, report_id: int) -> dict | None:
    query = """
        SELECT id, unit_id, shift, shift_start, shift_end, avg_efficiency,
               energy_saved_kwh, recommendation_summary, generated_at
        FROM shift_reports WHERE id = %s
    """
    try:
        with psycopg2.connect(_pg_dsn(dsn)) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (report_id,))
            row = cur.fetchone()
            if not row:
                return None
            item = dict(row)
            for k in ("shift_start", "shift_end", "generated_at"):
                if item.get(k):
                    item[k] = item[k].isoformat()
            return item
    except Exception:  # noqa: BLE001
        logger.exception("خوانش گزارش شیفت #%s ناموفق بود.", report_id)
        return None


def export_excel(reports: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Shift Reports"
    headers = [
        "id",
        "unit_id",
        "shift",
        "shift_start",
        "shift_end",
        "avg_efficiency",
        "energy_saved_kwh",
        "recommendation_summary",
        "generated_at",
    ]
    ws.append(headers)
    for r in reports:
        ws.append([r.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_pdf(reports: list[dict], title: str = "Khalij POS - Shift Energy Optimization Reports") -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = [
        Paragraph(title, styles["Title"]),
        Paragraph(f"Generated at: {datetime.utcnow().isoformat()}Z", styles["Normal"]),
        Spacer(1, 16),
    ]
    if not reports:
        story.append(Paragraph("No shift reports available.", styles["Normal"]))
    else:
        data = [["ID", "Shift", "Efficiency %", "Energy Saved kWh", "Summary"]]
        for r in reports:
            data.append(
                [
                    str(r.get("id", "")),
                    str(r.get("shift", "")),
                    str(r.get("avg_efficiency", "")),
                    str(r.get("energy_saved_kwh", "")),
                    str(r.get("recommendation_summary", ""))[:80],
                ]
            )
        table = Table(data, colWidths=[40, 60, 80, 90, 220])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2332")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f8")]),
                ]
            )
        )
        story.append(table)
    doc.build(story)
    return buf.getvalue()
