"""دروازه API (API Gateway) - نقطه ورود واحد داشبورد به میکروسرویس‌ها.

پیاده‌سازی احراز هویت دو مرحله‌ای اجباری (NFR-SEC-01) و مسیریابی درخواست‌ها
به سرویس‌های داخلی (Data Ingestion, Preprocessing, Prediction, Alerting).
"""
from __future__ import annotations

import json
import logging

import httpx
import redis
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from shared.logging_config import configure_logging
from shared.settings import get_settings

from .auth import (
    create_access_token,
    create_pending_otp_token,
    decode_token,
    get_current_operator,
    get_operator_by_employee_code,
    verify_otp_code,
    verify_password,
)

settings = get_settings()
configure_logging("api-gateway", settings.log_level)
logger = logging.getLogger(__name__)

app = FastAPI(title="Khalij POS - API Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_redis = redis.from_url(settings.redis_url, decode_responses=True)

_INTERNAL_SERVICES = {
    "data-ingestion": f"http://data-ingestion:{settings.data_ingestion_port}",
    "preprocessing": f"http://preprocessing:{settings.preprocessing_port}",
    "prediction": f"http://prediction:{settings.prediction_port}",
    "alerting": f"http://alerting:{settings.alerting_port}",
}


class LoginRequest(BaseModel):
    employee_code: str
    password: str


class OtpVerifyRequest(BaseModel):
    pending_token: str
    otp_code: str


class AcknowledgeAlertRequest(BaseModel):
    operator_id: int


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "api-gateway"}


@app.get("/health/services")
async def health_services() -> dict:
    """وضعیت سلامت تمام میکروسرویس‌های داخلی را جمع‌آوری می‌کند."""
    results: dict[str, str] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, base_url in _INTERNAL_SERVICES.items():
            try:
                response = await client.get(f"{base_url}/health")
                results[name] = "up" if response.status_code == 200 else "degraded"
            except httpx.HTTPError:
                results[name] = "down"
    return results


# ---------------------------------------------------------------------
# احراز هویت دو مرحله‌ای (NFR-SEC-01)
# ---------------------------------------------------------------------
@app.post("/auth/login")
async def login(body: LoginRequest) -> dict:
    """مرحله ۱: بررسی رمز عبور. در صورت موفقیت، توکن موقت برای مرحله OTP بازگردانده می‌شود."""
    operator = get_operator_by_employee_code(body.employee_code)
    if not operator or not verify_password(body.password, operator["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="کد کارمندی یا رمز عبور نادرست است.")

    if not operator["two_factor_enabled"] and not settings.two_factor_required:
        token = create_access_token(operator["id"], operator["employee_code"], operator["role"])
        return {"requires_otp": False, "access_token": token, "token_type": "bearer"}

    pending_token = create_pending_otp_token(operator["id"], operator["employee_code"])
    return {"requires_otp": True, "pending_token": pending_token}


@app.post("/auth/verify-otp")
async def verify_otp(body: OtpVerifyRequest) -> dict:
    """مرحله ۲: بررسی کد یک‌بارمصرف (TOTP) و صدور توکن دسترسی نهایی."""
    payload = decode_token(body.pending_token)
    if payload.get("token_type") != "pending_otp":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="توکن موقت نامعتبر است.")

    operator = get_operator_by_employee_code(payload["employee_code"])
    if not operator or not operator.get("otp_secret"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="احراز هویت دو مرحله‌ای فعال نیست.")

    if not verify_otp_code(operator["otp_secret"], body.otp_code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="کد یک‌بارمصرف نادرست است.")

    token = create_access_token(operator["id"], operator["employee_code"], operator["role"])
    return {"access_token": token, "token_type": "bearer"}


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
        response = await client.get(f"{_INTERNAL_SERVICES['alerting']}/alerts/recent", params={"limit": limit})
        response.raise_for_status()
        return response.json()


@app.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: int, body: AcknowledgeAlertRequest, operator: dict = Depends(get_current_operator)
) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.post(
            f"{_INTERNAL_SERVICES['alerting']}/alerts/{alert_id}/acknowledge",
            json={"operator_id": body.operator_id},
        )
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        return response.json()


@app.get("/recommendations/latest")
async def latest_recommendation(operator: dict = Depends(get_current_operator)) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        response = await client.get(f"{_INTERNAL_SERVICES['prediction']}/recommend/latest")
        response.raise_for_status()
        return response.json()
