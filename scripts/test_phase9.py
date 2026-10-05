"""Phase 9 unit tests: validation of Kubernetes / Kustomize manifests.

Run:
    pip install PyYAML
    python scripts/test_phase9.py
"""
from __future__ import annotations

import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "infra" / "k8s"


def _load_docs(path: Path) -> list[dict]:
    import yaml

    docs = []
    for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
        if doc:
            docs.append(doc)
    return docs


def test_kustomization_lists_resources() -> None:
    import yaml

    kust = yaml.safe_load((K8S / "base" / "kustomization.yaml").read_text(encoding="utf-8"))
    assert kust["kind"] == "Kustomization"
    resources = kust["resources"]
    for req in (
        "namespace.yaml",
        "apps/api-gateway.yaml",
        "apps/data-ingestion.yaml",
        "apps/prediction.yaml",
        "networking/ingress.yaml",
        "autoscaling/hpa.yaml",
    ):
        assert req in resources, f"missing {req}"
    for rel in resources:
        assert (K8S / "base" / rel).exists(), f"resource missing on disk: {rel}"
    print(f"[OK] kustomization resources={len(resources)}")


def test_app_probes() -> None:
    apps = ["api-gateway", "data-ingestion", "preprocessing", "prediction", "alerting"]
    for name in apps:
        docs = _load_docs(K8S / "base" / "apps" / f"{name}.yaml")
        dep = next(d for d in docs if d.get("kind") == "Deployment")
        container = dep["spec"]["template"]["spec"]["containers"][0]
        assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
        assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
        assert "envFrom" in container
        ann = dep["spec"]["template"]["metadata"].get("annotations", {})
        assert ann.get("prometheus.io/scrape") == "true"
    print("[OK] app probes + prometheus annotations")


def test_hpa_targets() -> None:
    docs = _load_docs(K8S / "base" / "autoscaling" / "hpa.yaml")
    hpas = [d for d in docs if d.get("kind") == "HorizontalPodAutoscaler"]
    names = {h["metadata"]["name"] for h in hpas}
    assert {"api-gateway", "data-ingestion", "preprocessing", "prediction", "alerting"} <= names
    for h in hpas:
        assert h["spec"]["minReplicas"] >= 1
        assert h["spec"]["maxReplicas"] >= h["spec"]["minReplicas"]
        assert h["spec"]["scaleTargetRef"]["kind"] == "Deployment"
    print(f"[OK] HPA count={len(hpas)}")


def test_ingress_tls() -> None:
    docs = _load_docs(K8S / "base" / "networking" / "ingress.yaml")
    ingress = next(d for d in docs if d.get("kind") == "Ingress")
    assert ingress["spec"]["tls"]
    assert ingress["spec"]["rules"][0]["host"] == "pos.khalij.local"
    assert ingress["spec"]["rules"][0]["http"]["paths"][0]["backend"]["service"]["name"] == "api-gateway"
    nps = [d for d in docs if d.get("kind") == "NetworkPolicy"]
    assert len(nps) >= 2
    print("[OK] ingress TLS + network policies")


def test_secrets_example() -> None:
    docs = _load_docs(K8S / "base" / "secrets.example.yaml")
    secret = docs[0]
    assert secret["kind"] == "Secret"
    keys = set(secret["stringData"].keys())
    for k in ("JWT_SECRET_KEY", "POSTGRES_DSN", "REDIS_URL", "INTERNAL_API_KEY", "INFLUXDB_TOKEN"):
        assert k in keys
    print("[OK] secrets.example keys")


def test_dev_overlay() -> None:
    import yaml

    kust = yaml.safe_load((K8S / "overlays" / "dev" / "kustomization.yaml").read_text(encoding="utf-8"))
    assert "../../base" in kust["resources"]
    print("[OK] dev overlay")


def test_deploy_scripts_exist() -> None:
    assert (ROOT / "scripts" / "deploy-k8s.sh").exists()
    assert (ROOT / "scripts" / "deploy-k8s.ps1").exists()
    print("[OK] deploy scripts")


if __name__ == "__main__":
    test_kustomization_lists_resources()
    test_app_probes()
    test_hpa_targets()
    test_ingress_tls()
    test_secrets_example()
    test_dev_overlay()
    test_deploy_scripts_exist()
    print("\nPhase 9: all unit tests passed.")
