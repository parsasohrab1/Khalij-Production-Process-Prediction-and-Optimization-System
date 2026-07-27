# Khalij POS — Kubernetes (فاز ۹)

مانیفست‌های declarative با **Kustomize** برای استقرار روی کلاستر (kind / minikube / EKS / AKS / GKE).

## ساختار

```
infra/k8s/
  base/                 # محیط پایه production-like
    apps/               # api-gateway, ingestion, preprocessing, prediction, alerting
    infra/              # postgres, redis, kafka, influxdb
    networking/         # Ingress TLS + NetworkPolicy
    autoscaling/        # HPA
    observability/      # Prometheus با kubernetes_sd
  overlays/dev/         # replicas کمتر برای توسعه
```

## پیش‌نیاز

- Docker
- `kubectl`
- کلاستر محلی (مثلاً `kind create cluster`) یا کلاستر ابری
- Ingress Controller (nginx): `kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/kind/deploy.yaml`

## استقرار سریع

```bash
# Linux/macOS
chmod +x scripts/deploy-k8s.sh
./scripts/deploy-k8s.sh          # base
./scripts/deploy-k8s.sh dev      # overlay توسعه

# Windows PowerShell
.\scripts\deploy-k8s.ps1
.\scripts\deploy-k8s.ps1 -Overlay dev
```

یا دستی:

```bash
cp infra/k8s/base/secrets.example.yaml infra/k8s/base/secrets.yaml
# ویرایش secrets.yaml

kubectl apply -k infra/k8s/base
# یا
kubectl apply -k infra/k8s/overlays/dev
```

## تصاویر

```
khalij/api-gateway:latest
khalij/data-ingestion:latest
khalij/preprocessing:latest
khalij/prediction:latest
khalij/alerting:latest
```

برای kind: پس از build، `kind load docker-image khalij/api-gateway:latest` (و بقیه).

## Probes

همه میکروسرویس‌ها:

- liveness: `GET /health/live`
- readiness: `GET /health/ready`

## مقیاس

HPA روی CPU برای gateway / ingestion / preprocessing / prediction / alerting.

Ingestion از `HOSTNAME` پاد برای شاردینگ (فاز ۷) استفاده می‌کند؛ `INGESTION_SHARD_COUNT` با تعداد replica هم‌تراز شود.

## Ingress

- Host: `pos.khalij.local`
- TLS secret: `khalij-pos-tls`
- در `/etc/hosts` یا CoreDNS: `pos.khalij.local` → IP اینگرس

## امنیت

- NetworkPolicy: data-plane فقط از داخل namespace
- Secrets جدا از ConfigMap
- `ENFORCE_PRODUCTION_SECRETS=true` در ConfigMap

⚠️ `secrets.example.yaml` را هرگز با مقادیر واقعی commit نکنید.
