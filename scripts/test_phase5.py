"""تست‌های واحد فاز ۵: داشبورد UX، WebSocket، TOTP QR، خروجی گزارش.

اجرا:
    python scripts/test_phase5.py
"""
from __future__ import annotations

import base64
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_module(service: str, module_name: str) -> ModuleType:
    path = ROOT / "services" / service / "app" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"phase5_{service}_{module_name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # پکیج مجازی تا importهای نسبی داخل ماژول نشکنند (در صورت نیاز)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_report_export_formats() -> None:
    report_export = _load_module("alerting", "report_export")

    sample = [
        {
            "id": 1,
            "unit_id": 1,
            "shift": "morning",
            "shift_start": "2026-07-24T06:00:00+00:00",
            "shift_end": "2026-07-24T14:00:00+00:00",
            "avg_efficiency": 71.2,
            "energy_saved_kwh": 120.5,
            "recommendation_summary": "کاهش دبی خوراک به 320",
            "generated_at": "2026-07-24T14:01:00+00:00",
        }
    ]
    xlsx = report_export.export_excel(sample)
    pdf = report_export.export_pdf(sample)
    assert xlsx[:2] == b"PK"
    assert pdf[:4] == b"%PDF"
    assert len(xlsx) > 100
    assert len(pdf) > 100
    empty_pdf = report_export.export_pdf([])
    assert empty_pdf[:4] == b"%PDF"
    print(f"[OK] report export xlsx={len(xlsx)}B pdf={len(pdf)}B")


def test_qrcode_generation() -> None:
    import io

    import pyotp
    import qrcode

    secret = pyotp.random_base32()
    uri = pyotp.TOTP(secret).provisioning_uri(name="demo-admin", issuer_name="Khalij POS")
    qr = qrcode.QRCode(version=1, box_size=4, border=2)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    raw = buf.getvalue()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    b64 = base64.b64encode(raw).decode("ascii")
    assert len(b64) > 50
    print(f"[OK] totp qr png={len(raw)}B secret_len={len(secret)}")


def test_realtime_token_validation() -> None:
    from jose import jwt

    from shared.settings import get_settings

    settings = get_settings()
    good = jwt.encode(
        {"sub": "1", "employee_code": "demo-admin", "token_type": "access"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    pending = jwt.encode(
        {"sub": "1", "employee_code": "demo-admin", "token_type": "pending_otp"},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )

    realtime = _load_module("api-gateway", "realtime")
    assert realtime._validate_ws_token(good) is not None
    assert realtime._validate_ws_token(good)["employee_code"] == "demo-admin"
    assert realtime._validate_ws_token(pending) is None
    assert realtime._validate_ws_token("not-a-token") is None
    print("[OK] websocket token validation")


def test_dashboard_static_exists() -> None:
    dash = ROOT / "services" / "api-gateway" / "app" / "static" / "dashboard.html"
    assert dash.exists()
    text = dash.read_text(encoding="utf-8")
    for needle in ("ws/live", "view-optimize", "btn-export-pdf", "auth/totp/setup", "view-control"):
        assert needle in text, f"missing {needle}"
    print("[OK] dashboard.html multipage + websocket hooks")


def test_gateway_modules_exist() -> None:
    assert (ROOT / "services" / "api-gateway" / "app" / "realtime.py").exists()
    assert (ROOT / "services" / "api-gateway" / "app" / "totp_setup.py").exists()
    assert (ROOT / "services" / "alerting" / "app" / "report_export.py").exists()
    totp = _load_module("api-gateway", "totp_setup")
    assert callable(totp.generate_totp_setup)
    print("[OK] gateway realtime/totp + alerting report_export modules")


if __name__ == "__main__":
    test_report_export_formats()
    test_qrcode_generation()
    test_realtime_token_validation()
    test_dashboard_static_exists()
    test_gateway_modules_exist()
    print("\nفاز ۵: همه تست‌های واحد پاس شدند.")
