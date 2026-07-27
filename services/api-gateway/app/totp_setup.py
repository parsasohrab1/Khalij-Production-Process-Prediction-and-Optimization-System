"""راه‌اندازی اولیه TOTP با QR Code برای اپراتورها (فاز ۵ / NFR-SEC-01)."""
from __future__ import annotations

import base64
import io
import logging

import psycopg2
import pyotp
import qrcode

from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _pg_dsn() -> str:
    return settings.postgres_dsn.replace("postgresql+psycopg2", "postgresql")


def generate_totp_setup(employee_code: str, issuer: str = "Khalij POS") -> dict | None:
    """ساخت secret جدید + URI + تصویر QR (Base64 PNG) برای ثبت در Authenticator."""
    try:
        with psycopg2.connect(_pg_dsn()) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, full_name, otp_secret FROM operators WHERE employee_code = %s",
                (employee_code,),
            )
            row = cur.fetchone()
            if not row:
                return None
            operator_id, full_name, existing_secret = row
            secret = existing_secret or pyotp.random_base32()
            if not existing_secret:
                cur.execute("UPDATE operators SET otp_secret = %s WHERE id = %s", (secret, operator_id))
                conn.commit()

        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(name=f"{employee_code} ({full_name})", issuer_name=issuer)

        qr = qrcode.QRCode(version=1, box_size=6, border=2)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "employee_code": employee_code,
            "otp_secret": secret,
            "otpauth_uri": provisioning_uri,
            "qr_code_png_base64": qr_b64,
            "instructions": "QR را با Google Authenticator / Authy اسکن کنید، سپس کد ۶ رقمی را برای ورود وارد کنید.",
        }
    except Exception:  # noqa: BLE001
        logger.exception("تولید QR برای TOTP ناموفق بود.")
        return None
