"""Shared security hardening (phase 6 / NFR-SEC-01, NFR-SEC-02).

- Role hierarchy (RBAC)
- Password policy
- Validation of sensitive keys in the production environment
- Inter-service authentication with an Internal API Key
"""
from __future__ import annotations

import logging
import os
import re
from typing import Iterable

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

ROLE_LEVEL = {"operator": 1, "supervisor": 2, "admin": 3}

_WEAK_JWT_DEFAULTS = {
    "",
    "change_me",
    "change_me_to_a_long_random_secret",
    "dev-secret-change-me",
}


def role_at_least(role: str | None, minimum: str) -> bool:
    return ROLE_LEVEL.get(role or "", 0) >= ROLE_LEVEL.get(minimum, 99)


def validate_password_policy(password: str) -> list[str]:
    """Operational password rules. Empty = acceptable."""
    errors: list[str] = []
    if len(password) < 10:
        errors.append("Password must be at least 10 characters.")
    if not re.search(r"[A-Z]", password):
        errors.append("At least one uppercase letter is required.")
    if not re.search(r"[a-z]", password):
        errors.append("At least one lowercase letter is required.")
    if not re.search(r"\d", password):
        errors.append("At least one digit is required.")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("At least one special character is required.")
    return errors


def assert_production_secrets(
    *,
    environment: str,
    jwt_secret_key: str,
    data_encryption_key: str | None = None,
    enforce: bool | None = None,
) -> list[str]:
    """In production rejects default keys. Returns the list of warnings."""
    env = (environment or "development").lower()
    must_enforce = enforce if enforce is not None else env in {"production", "prod", "staging"}
    warnings: list[str] = []

    if jwt_secret_key.strip() in _WEAK_JWT_DEFAULTS or len(jwt_secret_key.strip()) < 24:
        msg = "JWT_SECRET_KEY is weak or default."
        if must_enforce:
            raise RuntimeError(f"Production security check failed: {msg}")
        warnings.append(msg)

    key = (data_encryption_key if data_encryption_key is not None else os.getenv("DATA_ENCRYPTION_KEY", "")).strip()
    if not key:
        msg = "DATA_ENCRYPTION_KEY is not set (AES-256 at-rest disabled)."
        if must_enforce:
            raise RuntimeError(f"Production security check failed: {msg}")
        warnings.append(msg)

    for w in warnings:
        logger.warning("Security warning: %s", w)
    return warnings


def verify_internal_api_key(
    x_internal_api_key: str | None = Header(default=None, alias="X-Internal-Api-Key"),
) -> None:
    """Dependency for internal microservices — mandatory if the key is set in env."""
    expected = os.getenv("INTERNAL_API_KEY", "").strip()
    if not expected:
        return  # allowed without a key in development
    if not x_internal_api_key or x_internal_api_key != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The internal service key is invalid.",
        )


def install_internal_api_key_middleware(app, *, exempt_paths: Iterable[str] | None = None) -> None:
    """Internal key check middleware; /health is exempt by default."""
    from starlette.responses import JSONResponse

    exempt = set(
        exempt_paths
        or {
            "/health",
            "/health/live",
            "/health/ready",
            "/metrics",
            "/docs",
            "/openapi.json",
            "/redoc",
        }
    )

    @app.middleware("http")
    async def _internal_key_guard(request, call_next):
        if request.url.path in exempt:
            return await call_next(request)
        expected = os.getenv("INTERNAL_API_KEY", "").strip()
        if not expected:
            return await call_next(request)
        provided = request.headers.get("X-Internal-Api-Key")
        if provided != expected:
            return JSONResponse({"detail": "The internal service key is invalid."}, status_code=401)
        return await call_next(request)


def internal_headers() -> dict[str, str]:
    key = os.getenv("INTERNAL_API_KEY", "").strip()
    return {"X-Internal-Api-Key": key} if key else {}


def require_roles(operator: dict, allowed: Iterable[str]) -> None:
    role = operator.get("role")
    if role not in set(allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{role}' does not have permission for this operation.",
        )
