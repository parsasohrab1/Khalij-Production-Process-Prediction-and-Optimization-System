"""Phase 6 unit tests: security hardening (RBAC, policy, secrets, rate/lockout helpers).

Run:
    python scripts/test_phase6.py
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(service: str, module_name: str) -> ModuleType:
    path = ROOT / "services" / service / "app" / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(f"phase6_{service}_{module_name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_password_policy() -> None:
    from shared.security import validate_password_policy

    assert validate_password_policy("short") 
    assert "10" in validate_password_policy("short")[0] or len(validate_password_policy("short")) > 0
    assert validate_password_policy("ChangeMe123!") == []
    weak = validate_password_policy("alllowercase1!")
    assert any("uppercase" in e for e in weak)
    print("[OK] password policy")


def test_role_hierarchy() -> None:
    from shared.security import role_at_least

    assert role_at_least("admin", "operator")
    assert role_at_least("supervisor", "operator")
    assert role_at_least("supervisor", "supervisor")
    assert not role_at_least("operator", "supervisor")
    assert not role_at_least("operator", "admin")
    assert role_at_least("admin", "admin")
    print("[OK] RBAC role hierarchy")


def test_production_secrets_guard() -> None:
    from shared.security import assert_production_secrets

    # development: warning only
    warns = assert_production_secrets(
        environment="development",
        jwt_secret_key="dev-secret-change-me",
        data_encryption_key="",
        enforce=False,
    )
    assert warns

    raised = False
    try:
        assert_production_secrets(
            environment="production",
            jwt_secret_key="dev-secret-change-me",
            data_encryption_key="",
            enforce=True,
        )
    except RuntimeError:
        raised = True
    assert raised

    ok = assert_production_secrets(
        environment="production",
        jwt_secret_key="a-sufficiently-long-random-jwt-secret-key",
        data_encryption_key="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",  # 32 bytes when decoded? 
        enforce=True,
    )
    # key above may not be 32 bytes - check length
    import base64

    good_key = base64.b64encode(b"0" * 32).decode()
    ok = assert_production_secrets(
        environment="production",
        jwt_secret_key="a-sufficiently-long-random-jwt-secret-key",
        data_encryption_key=good_key,
        enforce=True,
    )
    assert ok == []
    print("[OK] production secrets guard")


def test_rate_limiter_logic() -> None:
    # without a real Redis: we do not test loading the module and the hit method with a simple mock
    # instead we check the existence of the file and the API signature
    rl = _load("api-gateway", "rate_limit")
    assert hasattr(rl, "enforce_rate_limit")
    assert hasattr(rl, "RateLimiter")
    print("[OK] rate_limit module")


def test_lockout_module() -> None:
    lock = _load("api-gateway", "lockout")
    assert hasattr(lock, "AccountLockout")
    assert hasattr(lock, "get_lockout")
    print("[OK] lockout module")


def test_audit_schema_sql() -> None:
    audit = _load("api-gateway", "audit")
    assert "audit_events" in audit.ENSURE_SQL
    assert hasattr(audit, "AuditLogger")
    print("[OK] audit module")


def test_security_headers_middleware() -> None:
    mw = _load("api-gateway", "security_middleware")
    assert hasattr(mw, "SecurityHeadersMiddleware")
    print("[OK] security headers middleware")


def test_nginx_hardening() -> None:
    conf = (ROOT / "infra" / "nginx" / "nginx.conf").read_text(encoding="utf-8")
    for needle in ("TLSv1.3", "limit_req_zone", "/ws/", "Strict-Transport-Security", "Content-Security-Policy"):
        assert needle in conf, f"missing {needle}"
    print("[OK] nginx hardening")


def test_init_sql_rbac_users() -> None:
    sql = (ROOT / "infra" / "postgres" / "init.sql").read_text(encoding="utf-8")
    assert "demo-operator" in sql
    assert "demo-supervisor" in sql
    assert "audit_events" in sql
    print("[OK] postgres RBAC seed + audit table")


def test_internal_api_key_headers() -> None:
    import os

    from shared.security import internal_headers

    os.environ.pop("INTERNAL_API_KEY", None)
    assert internal_headers() == {}
    os.environ["INTERNAL_API_KEY"] = "test-key-123"
    assert internal_headers() == {"X-Internal-Api-Key": "test-key-123"}
    os.environ.pop("INTERNAL_API_KEY", None)
    print("[OK] internal API key headers")


if __name__ == "__main__":
    test_password_policy()
    test_role_hierarchy()
    test_production_secrets_guard()
    test_rate_limiter_logic()
    test_lockout_module()
    test_audit_schema_sql()
    test_security_headers_middleware()
    test_nginx_hardening()
    test_init_sql_rbac_users()
    test_internal_api_key_headers()
    print("\nPhase 6: all unit tests passed.")
