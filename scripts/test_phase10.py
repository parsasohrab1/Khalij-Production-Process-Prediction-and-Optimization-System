"""Phase 10 unit tests: pilot package (config, docs, overlay, readiness).

Run:
    pip install PyYAML
    python scripts/test_phase10.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]


def test_pilot_yaml() -> None:
    import yaml

    cfg = yaml.safe_load((ROOT / "config" / "pilot.yaml").read_text(encoding="utf-8"))
    assert cfg["pilot"]["unit_id"] == 1
    assert cfg["pilot"]["mode"] in {"shadow", "assisted"}
    assert len(cfg["acceptance_criteria"]) >= 8
    assert "auto_apply_setpoints" in cfg["scope"]["features_disabled_until_signoff"]
    print(f"[OK] pilot.yaml criteria={len(cfg['acceptance_criteria'])}")


def test_docs_exist() -> None:
    for rel in (
        "docs/pilot/RUNBOOK.md",
        "docs/pilot/ACCEPTANCE.md",
        "docs/pilot/REPORT_TEMPLATE.md",
        "docker-compose.pilot.yml",
        "infra/k8s/overlays/pilot/kustomization.yaml",
    ):
        assert (ROOT / rel).exists(), rel
    runbook = (ROOT / "docs/pilot/RUNBOOK.md").read_text(encoding="utf-8")
    assert "Rollback" in runbook or "rollback" in runbook.lower()
    assert "AC-01" in (ROOT / "docs/pilot/ACCEPTANCE.md").read_text(encoding="utf-8")
    print("[OK] pilot docs + compose + k8s overlay")


def test_readiness_script() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pilot_readiness.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "READY" in proc.stdout
    print("[OK] pilot_readiness.py")


def test_smoke_offline() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "pilot_smoke.py"), "--offline"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ALL SMOKE CHECKS PASSED" in proc.stdout
    assert (ROOT / "docs/pilot/last_smoke_report.json").exists()
    print("[OK] pilot_smoke.py --offline")


def test_k8s_pilot_overlay() -> None:
    import yaml

    kust = yaml.safe_load(
        (ROOT / "infra/k8s/overlays/pilot/kustomization.yaml").read_text(encoding="utf-8")
    )
    assert "../../base" in kust["resources"]
    assert any(r.get("name") == "prediction" and r.get("count") == 2 for r in kust.get("replicas", []))
    print("[OK] k8s pilot overlay")


if __name__ == "__main__":
    test_pilot_yaml()
    test_docs_exist()
    test_readiness_script()
    test_smoke_offline()
    test_k8s_pilot_overlay()
    print("\nPhase 10: all unit tests passed.")
