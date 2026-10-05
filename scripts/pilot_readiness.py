"""Pilot readiness gate (phase 10) — checks the presence of deliverables and the validity of config/pilot.yaml.

Run:
    python scripts/pilot_readiness.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_PATHS = [
    "config/pilot.yaml",
    "docs/pilot/RUNBOOK.md",
    "docs/pilot/ACCEPTANCE.md",
    "docs/pilot/REPORT_TEMPLATE.md",
    "docker-compose.pilot.yml",
    "infra/k8s/overlays/pilot/kustomization.yaml",
    "scripts/pilot_smoke.py",
    "scripts/test_phase10.py",
    # previous phases (minimal)
    "shared/security.py",
    "shared/scaling.py",
    "shared/metrics.py",
    "shared/slo.py",
    "infra/k8s/base/kustomization.yaml",
    "services/api-gateway/app/static/dashboard.html",
]


def load_pilot_config() -> dict:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("PyYAML is required: pip install PyYAML") from exc
    path = ROOT / "config" / "pilot.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("pilot.yaml is invalid.")
    return data


def check_paths() -> list[str]:
    missing = []
    for rel in REQUIRED_PATHS:
        if not (ROOT / rel).exists():
            missing.append(rel)
    return missing


def check_pilot_schema(cfg: dict) -> list[str]:
    errors: list[str] = []
    pilot = cfg.get("pilot") or {}
    for key in ("name", "unit_id", "duration_days", "mode", "data_source_mode"):
        if key not in pilot:
            errors.append(f"pilot.{key} missing")
    if pilot.get("mode") not in {"shadow", "assisted"}:
        errors.append("pilot.mode must be shadow or assisted")
    ac = cfg.get("acceptance_criteria") or []
    if len(ac) < 8:
        errors.append(f"acceptance_criteria must have at least 8 items (currently {len(ac)})")
    ids = [a.get("id") for a in ac]
    for expected in ("AC-01", "AC-02", "AC-05", "AC-06", "AC-08"):
        if expected not in ids:
            errors.append(f"criterion {expected} not found")
    disabled = (cfg.get("scope") or {}).get("features_disabled_until_signoff") or []
    if "auto_apply_setpoints" not in disabled:
        errors.append("auto_apply_setpoints must remain disabled until signoff")
    gates = cfg.get("gates") or {}
    if "go_live" not in gates or "exit_pilot" not in gates:
        errors.append("gates.go_live and gates.exit_pilot are required")
    return errors


def main() -> int:
    print("=== Pilot Readiness Gate (phase 10) ===")
    missing = check_paths()
    if missing:
        print("[FAIL] Required files are missing:")
        for m in missing:
            print(f"  - {m}")
        return 1
    print(f"[OK] artifacts present ({len(REQUIRED_PATHS)})")

    cfg = load_pilot_config()
    errors = check_pilot_schema(cfg)
    if errors:
        print("[FAIL] pilot.yaml validation:")
        for e in errors:
            print(f"  - {e}")
        return 1

    pilot = cfg["pilot"]
    print(f"[OK] pilot={pilot['name']} unit={pilot['unit_id']} mode={pilot['mode']} days={pilot['duration_days']}")
    print(f"[OK] acceptance_criteria={len(cfg['acceptance_criteria'])}")
    print("\nREADY — you can proceed with Go-Live per docs/pilot/RUNBOOK.md.")
    print("Reminder: before a real site, move secrets away from their default values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
