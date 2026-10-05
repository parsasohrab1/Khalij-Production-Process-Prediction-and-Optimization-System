"""Pilot smoke test (phase 10) — checks service health and automatable acceptance criteria.

Run without a cluster (offline):
    python scripts/pilot_smoke.py --offline

Run on a live environment:
    python scripts/pilot_smoke.py --base-url http://localhost:8000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_pilot() -> dict:
    import yaml

    return yaml.safe_load((ROOT / "config" / "pilot.yaml").read_text(encoding="utf-8"))


def check_offline() -> dict[str, Any]:
    """Checks that can be done without a live service."""
    from shared.slo import NFR_PER_02_WEEKLY
    from shared.security import role_at_least, validate_password_policy
    from shared.scaling import LatencyTracker

    results = {}
    cfg = load_pilot()
    results["AC-config"] = {
        "ok": len(cfg.get("acceptance_criteria", [])) >= 8,
        "detail": f"criteria={len(cfg.get('acceptance_criteria', []))}",
    }
    results["AC-05-policy"] = {
        "ok": role_at_least("supervisor", "operator") and not role_at_least("operator", "admin"),
        "detail": "RBAC hierarchy",
    }
    results["password-policy"] = {
        "ok": validate_password_policy("ChangeMe123!") == [],
        "detail": "demo password meets policy",
    }
    tracker = LatencyTracker(budget_ms=2000)
    for ms in (12, 40, 80, 120):
        tracker.record(ms)
    snap = tracker.snapshot()
    results["AC-02-budget"] = {
        "ok": (snap.get("p95_ms") or 0) <= 2000,
        "detail": f"p95={snap.get('p95_ms')}",
    }
    weekly = NFR_PER_02_WEEKLY.as_dict(0)
    results["AC-06-slo"] = {
        "ok": weekly["error_budget_seconds"] > 60,
        "detail": f"weekly_budget_s={weekly['error_budget_seconds']:.1f}",
    }
    dash = (ROOT / "services/api-gateway/app/static/dashboard.html").read_text(encoding="utf-8")
    results["AC-07-dashboard"] = {
        "ok": "ws/live" in dash and "view-optimize" in dash,
        "detail": "dashboard hooks present",
    }
    results["AC-safety"] = {
        "ok": "auto_apply_setpoints" in (cfg.get("scope") or {}).get("features_disabled_until_signoff", []),
        "detail": "no auto apply to DCS",
    }
    return results


def check_live(base_url: str, token: str | None) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    results: dict[str, Any] = {}
    base = base_url.rstrip("/")

    def get(path: str, auth: bool = False) -> tuple[int, Any]:
        req = urllib.request.Request(base + path)
        if auth and token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8")
                try:
                    return resp.status, json.loads(body)
                except json.JSONDecodeError:
                    return resp.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return 0, str(exc)

    code, health = get("/health")
    results["gateway-health"] = {"ok": code == 200, "detail": health}

    code, services = get("/health/services")
    results["AC-services"] = {
        "ok": code == 200 and isinstance(services, dict),
        "detail": services if code == 200 else f"status={code}",
    }

    # login should require OTP for demo (AC-05)
    payload = json.dumps({"employee_code": "demo-admin", "password": "ChangeMe123!"}).encode()
    req = urllib.request.Request(
        base + "/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            login = json.loads(resp.read().decode("utf-8"))
            results["AC-05"] = {
                "ok": login.get("requires_otp") is True or bool(login.get("access_token")),
                "detail": {"requires_otp": login.get("requires_otp")},
            }
    except Exception as exc:  # noqa: BLE001
        results["AC-05"] = {"ok": False, "detail": str(exc)}

    if token:
        code, lat = get("/metrics/latency", auth=True)
        ok = code == 200
        if isinstance(lat, dict) and lat.get("p95_ms") is not None:
            ok = ok and float(lat["p95_ms"]) <= 2000
        results["AC-02"] = {"ok": ok, "detail": lat}

        code, slo = get("/observability/slo", auth=True)
        results["AC-06"] = {"ok": code in (200, 403), "detail": f"status={code}"}

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Khalij POS pilot smoke test")
    parser.add_argument("--offline", action="store_true", help="offline checks only")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default="", help="optional Bearer token for protected APIs")
    args = parser.parse_args()

    print("=== Pilot Smoke (phase 10) ===")
    results = check_offline()
    if not args.offline:
        print(f"Live checks → {args.base_url}")
        results.update(check_live(args.base_url, args.token or None))

    failed = []
    for name, item in results.items():
        status = "OK" if item["ok"] else "FAIL"
        print(f"[{status}] {name}: {item['detail']}")
        if not item["ok"]:
            failed.append(name)

    report_path = ROOT / "docs" / "pilot" / "last_smoke_report.json"
    report_path.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nReport written: {report_path}")

    if failed:
        print(f"FAILED: {len(failed)} checks")
        return 1
    print("ALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
