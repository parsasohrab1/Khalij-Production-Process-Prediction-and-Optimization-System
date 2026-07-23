"""احراز هویت اپراتورها با رمز عبور + احراز هویت دو مرحله‌ای اجباری (NFR-SEC-01)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
import psycopg2.extras
import pyotp
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# نوع توکن موقت "pending_otp" فقط برای مرحله اول ورود معتبر است و دسترسی به API را نمی‌دهد
_PENDING_OTP_TOKEN_TYPE = "pending_otp"
_ACCESS_TOKEN_TYPE = "access"


def _pg_dsn() -> str:
    return settings.postgres_dsn.replace("postgresql+psycopg2", "postgresql")


def get_operator_by_employee_code(employee_code: str) -> dict | None:
    query = """
        SELECT id, employee_code, full_name, password_hash, otp_secret, role, two_factor_enabled
        FROM operators WHERE employee_code = %s
    """
    try:
        with psycopg2.connect(_pg_dsn()) as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, (employee_code,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:  # noqa: BLE001
        logger.exception("خوانش اطلاعات اپراتور از PostgreSQL ناموفق بود.")
        return None


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def verify_otp_code(otp_secret: str, code: str) -> bool:
    return pyotp.TOTP(otp_secret).verify(code, valid_window=1)


def _create_token(subject: dict, token_type: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **subject,
        "token_type": token_type,
        "iat": now,
        "exp": now + timedelta(minutes=expires_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_pending_otp_token(operator_id: int, employee_code: str) -> str:
    return _create_token(
        {"sub": str(operator_id), "employee_code": employee_code}, _PENDING_OTP_TOKEN_TYPE, expires_minutes=5
    )


def create_access_token(operator_id: int, employee_code: str, role: str) -> str:
    return _create_token(
        {"sub": str(operator_id), "employee_code": employee_code, "role": role},
        _ACCESS_TOKEN_TYPE,
        expires_minutes=settings.access_token_expire_minutes,
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="توکن نامعتبر یا منقضی شده است.") from exc


async def get_current_operator(token: str = Depends(_oauth2_scheme)) -> dict:
    payload = decode_token(token)
    if payload.get("token_type") != _ACCESS_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="این توکن هنوز مرحله احراز هویت دو مرحله‌ای را کامل نکرده است.",
        )
    return payload


def require_role(*roles: str):
    async def _dependency(operator: dict = Depends(get_current_operator)) -> dict:
        if roles and operator.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="دسترسی کافی نیست.")
        return operator

    return _dependency
