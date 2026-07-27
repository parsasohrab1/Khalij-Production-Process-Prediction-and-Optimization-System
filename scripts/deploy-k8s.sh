#!/usr/bin/env bash
# استقرار Khalij POS روی Kubernetes (فاز ۹)
# پیش‌نیاز: kubectl, kustomize (یا kubectl با kustomize داخلی), docker
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
K8S="$ROOT/infra/k8s"
OVERLAY="${1:-base}"

echo "==> Building images..."
docker build -t khalij/api-gateway:latest -f "$ROOT/services/api-gateway/Dockerfile" "$ROOT"
docker build -t khalij/data-ingestion:latest -f "$ROOT/services/data-ingestion/Dockerfile" "$ROOT"
docker build -t khalij/preprocessing:latest -f "$ROOT/services/preprocessing/Dockerfile" "$ROOT"
docker build -t khalij/prediction:latest -f "$ROOT/services/prediction/Dockerfile" "$ROOT"
docker build -t khalij/alerting:latest -f "$ROOT/services/alerting/Dockerfile" "$ROOT"

if [[ ! -f "$K8S/base/secrets.yaml" ]]; then
  echo "==> Creating secrets.yaml from example (لطفاً مقادیر را عوض کنید)"
  cp "$K8S/base/secrets.example.yaml" "$K8S/base/secrets.yaml"
fi

# kustomization از secrets.example استفاده می‌کند؛ برای secrets.yaml واقعی پچ می‌کنیم
TARGET="$K8S/base"
if [[ "$OVERLAY" == "dev" ]]; then
  TARGET="$K8S/overlays/dev"
fi

echo "==> Applying kustomize ($TARGET)..."
kubectl apply -k "$TARGET"

echo "==> Waiting for api-gateway..."
kubectl -n khalij-pos rollout status deployment/api-gateway --timeout=180s || true
kubectl -n khalij-pos get pods,svc,ingress,hpa
echo "Done. Ingress host: https://pos.khalij.local (DNS/hosts را تنظیم کنید)."
