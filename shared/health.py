"""اندپوینت‌های liveness / readiness مشترک (فاز ۷ / NFR-PER-02)."""
from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Response, status


def install_health_probes(
    app: FastAPI,
    *,
    service_name: str,
    ready_check: Callable[[], bool] | None = None,
    details: Callable[[], dict] | None = None,
) -> None:
    """
    /health/live  — فرایند زنده است
    /health/ready — وابستگی‌ها آماده‌اند (برای orchestration)
    /health       — سازگاری با نسخه‌های قبلی
    """

    @app.get("/health/live")
    async def live() -> dict:
        return {"status": "alive", "service": service_name}

    @app.get("/health/ready")
    async def ready() -> Response:
        ok = True if ready_check is None else bool(ready_check())
        body = {"status": "ready" if ok else "not_ready", "service": service_name}
        if details:
            try:
                body["details"] = details()
            except Exception as exc:  # noqa: BLE001
                body["details_error"] = str(exc)
                ok = False
        return Response(
            content=__import__("json").dumps(body, ensure_ascii=False),
            status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json",
        )
