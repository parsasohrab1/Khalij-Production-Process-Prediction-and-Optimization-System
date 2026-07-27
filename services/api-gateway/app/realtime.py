"""پخش زنده داده‌ها از طریق WebSocket برای داشبورد اپراتور (فاز ۵ / R-GEN-03)."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import redis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from shared.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter()

_CONTROL_ROOM_CACHE_KEY = "control_room:recent_alerts"


def _validate_ws_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("token_type") != "access":
            return None
        # بررسی ابطال (logout)
        jti = payload.get("jti")
        if jti:
            r = redis.from_url(settings.redis_url, decode_responses=True)
            try:
                if r.exists(f"auth:revoke:{jti}"):
                    return None
            finally:
                try:
                    r.close()
                except Exception:  # noqa: BLE001
                    pass
        return payload
    except JWTError:
        return None


@router.websocket("/ws/live")
async def live_stream(websocket: WebSocket, token: str = "", unit_id: int = 1) -> None:
    """استریم زنده سنسورها، پیش‌بینی، توصیه و هشدارهای اتاق کنترل."""
    await websocket.accept()
    operator = _validate_ws_token(token)
    if operator is None:
        await websocket.send_json({"type": "error", "message": "توکن نامعتبر است."})
        await websocket.close(code=4401)
        return

    r = redis.from_url(settings.redis_url, decode_responses=True)
    await websocket.send_json(
        {"type": "connected", "operator": operator.get("employee_code"), "unit_id": unit_id}
    )

    try:
        while True:
            sensors_raw = r.get(f"latest_reading:{unit_id}")
            prediction_raw = r.get(f"latest_prediction:{unit_id}")
            alerts_raw = r.lrange(_CONTROL_ROOM_CACHE_KEY, 0, 19)

            payload = {
                "type": "snapshot",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sensors": json.loads(sensors_raw) if sensors_raw else {},
                "prediction": json.loads(prediction_raw) if prediction_raw else {},
                "alerts": [json.loads(a) for a in alerts_raw],
            }
            # توصیه از Redis اگر کش شده باشد
            rec_raw = r.get(f"latest_recommendation:{unit_id}")
            if rec_raw:
                payload["recommendation"] = json.loads(rec_raw)

            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        logger.info("WebSocket قطع شد: %s", operator.get("employee_code"))
    except Exception:  # noqa: BLE001
        logger.exception("خطا در استریم WebSocket")
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            r.close()
        except Exception:  # noqa: BLE001
            pass
