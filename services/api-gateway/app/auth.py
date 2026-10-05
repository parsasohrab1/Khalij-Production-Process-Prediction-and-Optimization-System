"""Operator authentication with password + mandatory two-factor authentication (NFR-SEC-01).

Phase 6: support for token revocation (logout), minimum-role-based RBAC, and jti.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import psycopg2
import psycopg2.extras
import pyotp
import redis
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from shared.security import role_at_least
from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_PENDING_OTP_TOKEN_TYPE = "pending_otp"
_ACCESS_TOKEN_TYPE = "access"
_REVOKE_PREFIX = "auth:revoke:"

_redis = redis.from_url(settings.redis_url, decode_responses=True)


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
        logger.exception("Reading operator information from PostgreSQL failed.")
        return None


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_otp_code(otp_secret: str, code: str) -> bool:
    return pyotp.TOTP(otp_secret).verify(code, valid_window=1)


def _create_token(subject: dict, token_type: str, expires_minutes: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **subject,
        "token_type": token_type,
        "jti": str(uuid.uuid4()),
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The token is invalid or expired.") from exc


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def revoke_token(token: str) -> None:
    """Revoke the token until its expiry (logout)."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
            options={"verify_exp": False},
        )
        jti = payload.get("jti") or _token_fingerprint(token)
        exp = payload.get("exp")
        ttl = 60
        if isinstance(exp, (int, float)):
            ttl = max(60, int(exp - datetime.now(timezone.utc).timestamp()))
        _redis.setex(f"{_REVOKE_PREFIX}{jti}", ttl, "1")
    except Exception:  # noqa: BLE001
        logger.debug("Token revocation failed.", exc_info=True)


def is_token_revoked(payload: dict) -> bool:
    jti = payload.get("jti")
    if not jti:
        return False
    try:
        return bool(_redis.exists(f"{_REVOKE_PREFIX}{jti}"))
    except Exception:  # noqa: BLE001
        return False


async def get_current_operator(token: str = Depends(_oauth2_scheme)) -> dict:
    payload = decode_token(token)
    if payload.get("token_type") != _ACCESS_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token has not yet completed the two-factor authentication step.",
        )
    if is_token_revoked(payload):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="The token has been revoked.")
    return payload


def require_role(*roles: str):
    async def _dependency(operator: dict = Depends(get_current_operator)) -> dict:
        if roles and operator.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient access.")
        return operator

    return _dependency


def require_min_role(minimum: str):
    """Minimum role level: operator < supervisor < admin."""

    async def _dependency(operator: dict = Depends(get_current_operator)) -> dict:
        if not role_at_least(operator.get("role"), minimum):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Minimum required role: {minimum}",
            )
        return operator

    return _dependency
