"""دروازه API (API Gateway) - نقطه ورود واحد داشبورد به میکروسرویس‌ها.

پیاده‌سازی احراز هویت دو مرحله‌ای اجباری (NFR-SEC-01)، مسیریابی درخواست‌ها،
و سخت‌سازی امنیتی فاز ۶ (RBAC، rate limit، lockout، audit، security headers).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from shared.health import install_health_probes
from shared.logging_config import configure_logging
from shared.metrics import install_prometheus_metrics, prometheus_available
from shared.security import assert_production_secrets, internal_headers, validate_password_policy
from shared.settings import get_settings
from shared.slo import NFR_PER_02_MONTHLY, NFR_PER_02_WEEKLY
from shared.tracing import setup_tracing

from .audit import get_audit
from .auth import (
    create_access_token,
    create_pending_otp_token,
    decode_token,
    get_current_operator,
    get_operator_by_employee_code,
    hash_password,
    require_min_role,
    revoke_token,
    verify_otp_code,
    verify_password,
)
from .lockout import get_lockout
from .rate_limit import enforce_rate_limit
from .realtime import router as realtime_router
from .security_middleware import SecurityHeadersMiddleware
from .totp_setup import generate_totp_setup

settings = get_settings()
configure_logging("api-gateway", settings.log_level)
logger = logging.getLogger(__name__)

# همگام‌سازی کلید داخلی با env برای کلاینت‌های httpx
if settings.internal_api_key and not os.getenv("INTERNAL_API_KEY"):
    os.environ["INTERNAL_API_KEY"] = settings.internal_api_key

app = FastAPI(title="Khalij POS - API Gateway", version="8.0.0")
install_prometheus_metrics(app, service_name="api-gateway")
setup_tracing("api-gateway", app)
install_health_probes(app, service_name="api-gateway", ready_check=lambda: True)

_cors_origins = [o.strip() for o in settings.cors_allow_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins if _cors_origins != ["*"] else ["*"],
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Internal-Api-Key"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.include_router(realtime_router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

_redis = redis.from_url(settings.redis_url, decode_responses=True)
_audit = get_audit()
_lockout = get_lockout()
_oauth2_logout = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

_INTERNAL_SERVICES = {
    "data-ingestion": f"http://data-ingestion:{settings.data_ingestion_port}",
    "preprocessing": f"http://preprocessing:{settings.preprocessing_port}",
    "prediction": f"http://prediction:{settings.prediction_port}",
    "alerting": f"http://alerting:{settings.alerting_port}",
}


def _client_meta(request: Request) -> dict:
    return {
        "ip_address": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
    }


def _proxy_headers() -> dict[str, str]:
    return internal_headers()


@app.on_event("startup")
async def startup_security() -> None:
    warnings = assert_production_secrets(
        environment=settings.environment,
        jwt_secret_key=settings.jwt_secret_key,
        data_encryption_key=settings.data_encryption_key or os.getenv("DATA_ENCRYPTION_KEY", ""),
        enforce=settings.enforce_production_secrets
        or settings.environment.lower() in {"production", "prod"},
    )
    _audit.ensure_schema()
    logger.info("API Gateway security startup complete. warnings=%s", warnings)


class LoginRequest(BaseModel):
    employee_code: str
    password: str


class OtpVerifyRequest(BaseModel):
    pending_token: str
    otp_code: str


class TotpSetupRequest(BaseModel):
    employee_code: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)


class AcknowledgeAlertRequest(BaseModel):
    operator_id: int


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway", "security_phase": 6, "observability_phase": 8}


@app.get("/observability/status")
async def observability_status(operator: dict = Depends(require_min_role("supervisor"))) -> dict:
    return {
        "prometheus_client": prometheus_available(),
        "otel_endpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
        "log_format": os.getenv("LOG_FORMAT", "auto"),
        "grafana_url": os.getenv("GRAFANA_URL", "http://localhost:3000"),
        "prometheus_url": os.getenv("PROMETHEUS_URL", "http://localhost:9090"),
        "slo": {
            "weekly": NFR_PER_02_WEEKLY.as_dict(),
            "monthly": NFR_PER_02_MONTHLY.as_dict(),
        },
    }


@app.get("/observability/slo")
async def observability_slo(
    downtime_seconds: float = 0.0,
    operator: dict = Depends(require_min_role("supervisor")),
) -> dict:
    """محاسبه بودجه خطای NFR-PER-02 (۹۹.۹۹٪)."""
    return {
        "nfr": "NFR-PER-02",
        "target": "99.99% availability",
        "weekly": NFR_PER_02_WEEKLY.as_dict(downtime_seconds),
        "monthly": NFR_PER_02_MONTHLY.as_dict(downtime_seconds),
        "note": "downtime_seconds را از Prometheus (time() - timestamp(up==0)) یا Alertmanager بگیرید.",
    }


@app.get("/")
@app.get("/dashboard")
async def dashboard_page():
    """داشبورد مانیتورینگ با نمایش هشدارهای پیش‌بینی‌شده (R-GEN-03)."""
    return FileResponse(_STATIC_DIR / "dashboard.html")


@app.get("/health/services")
async def health_services() -> dict:
    results: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, base_url in _INTERNAL_SERVICES.items():
            try:
                response = await client.get(f"{base_url}/health", headers=_proxy_headers())
                results[name] = "up" if response.status_code == 200 else "degraded"
            except httpx.HTTPError:
                results[name] = "down"
    return results


# ---------------------------------------------------------------------
# احراز هویت دو مرحله‌ای + سخت‌سازی فاز ۶
# ---------------------------------------------------------------------
@app.post("/auth/login")
async def login(body: LoginRequest, request: Request) -> dict:
    enforce_rate_limit(
        request,
        scope="login",
        limit=settings.rate_limit_login_per_minute,
        window_seconds=60,
    )
    meta = _client_meta(request)
    locked, ttl = _lockout.is_locked(body.employee_code)
    if locked:
        _audit.log(
            event_type="auth",
            action="login_blocked_lockout",
            success=False,
            actor_code=body.employee_code,
            details={"retry_after_s": ttl},
            **meta,
        )
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"حساب موقتاً قفل است. {ttl} ثانیه دیگر تلاش کنید.",
            headers={"Retry-After": str(ttl)},
        )

    operator = get_operator_by_employee_code(body.employee_code)
    if not operator or not verify_password(body.password, operator["password_hash"]):
        fails = _lockout.register_failure(body.employee_code)
        _audit.log(
            event_type="auth",
            action="login_failed",
            success=False,
            actor_code=body.employee_code,
            details={"failures": fails},
            **meta,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="کد کارمندی یا رمز عبور نادرست است.")

    _lockout.clear(body.employee_code)
    _audit.log(
        event_type="auth",
        action="login_password_ok",
        success=True,
        actor_code=operator["employee_code"],
        actor_role=operator["role"],
        **meta,
    )

    if not operator["two_factor_enabled"] and not settings.two_factor_required:
        token = create_access_token(operator["id"], operator["employee_code"], operator["role"])
        return {"requires_otp": False, "access_token": token, "token_type": "bearer"}

    pending_token = create_pending_otp_token(operator["id"], operator["employee_code"])
    return {"requires_otp": True, "pending_token": pending_token}


@app.post("/auth/verify-otp")
async def verify_otp(body: OtpVerifyRequest, request: Request) -> dict:
    enforce_rate_limit(request, scope="otp", limit=settings.rate_limit_login_per_minute, window_seconds=60)
    meta = _client_meta(request)
    payload = decode_token(body.pending_token)
    if payload.get("token_type") != "pending_otp":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="توکن موقت نامعتبر است.")

    employee_code = payload["employee_code"]
    locked, ttl = _lockout.is_locked(employee_code)
    if locked:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"حساب موقتاً قفل است. {ttl} ثانیه دیگر تلاش کنید.",
            headers={"Retry-After": str(ttl)},
        )

    operator = get_operator_by_employee_code(employee_code)
    if not operator or not operator.get("otp_secret"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="احراز هویت دو مرحله‌ای فعال نیست.")

    if not verify_otp_code(operator["otp_secret"], body.otp_code):
        fails = _lockout.register_failure(employee_code)
        _audit.log(
            event_type="auth",
            action="otp_failed",
            success=False,
            actor_code=employee_code,
            details={"failures": fails},
            **meta,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="کد یک‌بارمصرف نادرست است.")

    _lockout.clear(employee_code)
    token = create_access_token(operator["id"], operator["employee_code"], operator["role"])
    _audit.log(
        event_type="auth",
        action="login_success",
        success=True,
        actor_code=operator["employee_code"],
        actor_role=operator["role"],
        **meta,
    )
    return {"access_token": token, "token_type": "bearer", "role": operator["role"]}


@app.post("/auth/logout")
async def logout(
    request: Request,
    token: str | None = Depends(_oauth2_logout),
    operator: dict = Depends(get_current_operator),
) -> dict:
    raw = token or (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if raw:
        revoke_token(raw)
    _audit.log(
        event_type="auth",
        action="logout",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        **_client_meta(request),
    )
    return {"logged_out": True}


@app.post("/auth/change-password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    operator: dict = Depends(get_current_operator),
) -> dict:
    errors = validate_password_policy(body.new_password)
    if errors:
        raise HTTPException(status_code=400, detail={"policy_errors": errors})
    row = get_operator_by_employee_code(operator["employee_code"])
    if not row or not verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="رمز فعلی نادرست است.")
    new_hash = hash_password(body.new_password)
    dsn = settings.postgres_dsn.replace("postgresql+psycopg2", "postgresql")
    import psycopg2

    with psycopg2.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE operators SET password_hash = %s WHERE employee_code = %s",
            (new_hash, operator["employee_code"]),
        )
        conn.commit()
    _audit.log(
        event_type="auth",
        action="password_changed",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        **_client_meta(request),
    )
    return {"password_changed": True}


@app.post("/auth/totp/setup")
async def totp_setup_with_password(body: TotpSetupRequest, request: Request) -> dict:
    enforce_rate_limit(request, scope="totp_setup", limit=5, window_seconds=60)
    operator = get_operator_by_employee_code(body.employee_code)
    if not operator or not verify_password(body.password, operator["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="کد کارمندی یا رمز عبور نادرست است.")
    setup = generate_totp_setup(body.employee_code)
    if setup is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="تولید QR ناموفق بود.")
    _audit.log(
        event_type="auth",
        action="totp_setup",
        success=True,
        actor_code=body.employee_code,
        actor_role=operator.get("role"),
        **_client_meta(request),
    )
    return setup


@app.get("/auth/totp/setup")
async def totp_setup_authenticated(operator: dict = Depends(get_current_operator)) -> dict:
    setup = generate_totp_setup(operator["employee_code"])
    if setup is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="تولید QR ناموفق بود.")
    return setup


@app.middleware("http")
async def api_rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if (
        path.startswith("/auth/")
        or path.startswith("/health")
        or path.startswith("/metrics")
        or path.startswith("/static")
        or path.startswith("/ws")
        or path in {"/", "/dashboard"}
    ):
        return await call_next(request)
    try:
        enforce_rate_limit(
            request,
            scope="api",
            limit=settings.rate_limit_api_per_minute,
            window_seconds=60,
        )
    except HTTPException as exc:
        return Response(
            content=json.dumps({"detail": exc.detail}, ensure_ascii=False),
            status_code=exc.status_code,
            media_type="application/json",
            headers=exc.headers or {},
        )
    return await call_next(request)


# ---------------------------------------------------------------------
# داشبورد مانیتورینگ (R-GEN-03)
# ---------------------------------------------------------------------
@app.get("/sensors/latest")
async def latest_sensor_reading(unit_id: int = 1, operator: dict = Depends(get_current_operator)) -> dict:
    cached = _redis.get(f"latest_reading:{unit_id}")
    return json.loads(cached) if cached else {}


@app.get("/predictions/latest")
async def latest_prediction(unit_id: int = 1, operator: dict = Depends(get_current_operator)) -> dict:
    cached = _redis.get(f"latest_prediction:{unit_id}")
    return json.loads(cached) if cached else {}


@app.get("/alerts/control-room")
async def control_room_alerts(limit: int = 50, operator: dict = Depends(get_current_operator)) -> list[dict]:
    raw_items = _redis.lrange("control_room:recent_alerts", 0, limit - 1)
    return [json.loads(item) for item in raw_items]


@app.get("/alerts/recent")
async def recent_alerts(limit: int = 50, operator: dict = Depends(get_current_operator)) -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['alerting']}/alerts/recent",
            params={"limit": limit},
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int,
    body: AcknowledgeAlertRequest,
    request: Request,
    operator: dict = Depends(get_current_operator),
) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['alerting']}/alerts/{alert_id}/acknowledge",
            json={"operator_id": body.operator_id},
            headers=_proxy_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        result = response.json()
    _audit.log(
        event_type="alert",
        action="acknowledge",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        resource=f"alert:{alert_id}",
        **_client_meta(request),
    )
    return result


@app.get("/recommendations/latest")
async def latest_recommendation(operator: dict = Depends(get_current_operator)) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['prediction']}/recommend/latest",
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


class OptimizeBody(BaseModel):
    reactor_temp_c: float
    pressure_bar: float
    feed_flow_m3h: float
    unit_id: int = 1
    persist: bool = True


class WhatIfBody(BaseModel):
    reactor_temp_c: float
    current_pressure_bar: float
    current_feed_flow: float
    proposed_pressure_bar: float
    proposed_feed_flow: float


class ApplyBody(BaseModel):
    recommendation_id: int
    operator_id: int = 1
    run_whatif_first: bool = True


class FeedbackBody(BaseModel):
    recommendation_id: int
    actual_efficiency: float
    operator_id: int | None = None


@app.post("/optimize")
async def gateway_optimize(
    body: OptimizeBody,
    request: Request,
    operator: dict = Depends(require_min_role("operator")),
) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['prediction']}/optimize",
            json=body.model_dump(),
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        result = response.json()
    _audit.log(
        event_type="optimize",
        action="optimize",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        details={"unit_id": body.unit_id},
        **_client_meta(request),
    )
    return result


@app.post("/optimize/whatif")
async def gateway_whatif(body: WhatIfBody, operator: dict = Depends(require_min_role("operator"))) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['prediction']}/optimize/whatif",
            json=body.model_dump(),
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.post("/optimize/apply")
async def gateway_apply(
    body: ApplyBody,
    request: Request,
    operator: dict = Depends(require_min_role("supervisor")),
) -> dict:
    payload = body.model_dump()
    if not payload.get("operator_id"):
        payload["operator_id"] = int(operator.get("sub", 1))
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['prediction']}/optimize/apply",
            json=payload,
            headers=_proxy_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.json())
        result = response.json()
    _audit.log(
        event_type="optimize",
        action="apply",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        resource=f"recommendation:{body.recommendation_id}",
        details=result if isinstance(result, dict) else {},
        **_client_meta(request),
    )
    return result


@app.post("/optimize/feedback")
async def gateway_feedback(
    body: FeedbackBody,
    request: Request,
    operator: dict = Depends(require_min_role("supervisor")),
) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['prediction']}/optimize/feedback",
            json=body.model_dump(),
            headers=_proxy_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        result = response.json()
    _audit.log(
        event_type="optimize",
        action="feedback",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        resource=f"recommendation:{body.recommendation_id}",
        **_client_meta(request),
    )
    return result


@app.get("/optimize/feedback/summary")
async def gateway_feedback_summary(limit: int = 50, operator: dict = Depends(get_current_operator)) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['prediction']}/optimize/feedback/summary",
            params={"limit": limit},
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.get("/quality/stats")
async def quality_stats(operator: dict = Depends(require_min_role("supervisor"))) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['preprocessing']}/quality/stats",
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.get("/models/comparison")
async def gateway_model_comparison(operator: dict = Depends(require_min_role("supervisor"))) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['prediction']}/models/comparison",
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.get("/metrics/latency")
async def gateway_prediction_latency(operator: dict = Depends(get_current_operator)) -> dict:
    """متریک تأخیر پیش‌بینی (فاز ۷ / NFR-PER-01)."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['prediction']}/metrics/latency",
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.get("/scale/ingestion")
async def gateway_scale_ingestion(operator: dict = Depends(require_min_role("supervisor"))) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['data-ingestion']}/scale/info",
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.post("/models/train")
async def gateway_train_model(
    request: Request,
    unit_id: int = 1,
    operator: dict = Depends(require_min_role("admin")),
) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['prediction']}/train",
            params={"unit_id": unit_id},
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        result = response.json()
    _audit.log(
        event_type="mlops",
        action="train",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        details={"unit_id": unit_id},
        **_client_meta(request),
    )
    return result


@app.get("/reports/shift/recent")
async def recent_shift_reports(limit: int = 20, operator: dict = Depends(get_current_operator)) -> list[dict]:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['alerting']}/reports/shift/recent",
            params={"limit": limit},
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        return response.json()


@app.post("/reports/shift/generate")
async def generate_shift_report(
    request: Request,
    unit_id: int = 1,
    operator: dict = Depends(require_min_role("supervisor")),
) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['alerting']}/reports/shift/generate",
            params={"unit_id": unit_id},
            headers=_proxy_headers(),
        )
        response.raise_for_status()
        result = response.json()
    _audit.log(
        event_type="report",
        action="generate_shift",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        **_client_meta(request),
    )
    return result


@app.get("/reports/shift/export")
async def export_shift_reports(
    request: Request,
    format: str = "xlsx",
    limit: int = 50,
    operator: dict = Depends(require_min_role("supervisor")),
) -> Response:
    fmt = format.lower().strip()
    if fmt not in {"pdf", "xlsx", "excel"}:
        raise HTTPException(status_code=400, detail="فرمت باید pdf یا xlsx باشد.")
    if fmt == "excel":
        fmt = "xlsx"
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{_INTERNAL_SERVICES['alerting']}/reports/shift/export",
            params={"format": fmt, "limit": limit},
            headers=_proxy_headers(),
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        media = (
            "application/pdf"
            if fmt == "pdf"
            else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        filename = f"shift_reports.{fmt}"
    _audit.log(
        event_type="report",
        action="export",
        success=True,
        actor_code=operator.get("employee_code"),
        actor_role=operator.get("role"),
        details={"format": fmt},
        **_client_meta(request),
    )
    return Response(
        content=response.content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/security/audit")
async def security_audit_log(limit: int = 50, operator: dict = Depends(require_min_role("admin"))) -> list[dict]:
    return _audit.list_recent(limit)


@app.get("/security/status")
async def security_status(operator: dict = Depends(require_min_role("admin"))) -> dict:
    return {
        "two_factor_required": settings.two_factor_required,
        "cors_allow_origins": _cors_origins,
        "login_max_failures": settings.login_max_failures,
        "login_lockout_seconds": settings.login_lockout_seconds,
        "rate_limit_login_per_minute": settings.rate_limit_login_per_minute,
        "rate_limit_api_per_minute": settings.rate_limit_api_per_minute,
        "internal_api_key_configured": bool(settings.internal_api_key or os.getenv("INTERNAL_API_KEY")),
        "encryption_key_configured": bool(settings.data_encryption_key or os.getenv("DATA_ENCRYPTION_KEY")),
        "enforce_production_secrets": settings.enforce_production_secrets,
        "environment": settings.environment,
    }
