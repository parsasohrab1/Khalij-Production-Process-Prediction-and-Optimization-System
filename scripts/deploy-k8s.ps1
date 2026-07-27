# استقرار Khalij POS روی Kubernetes (فاز ۹) — PowerShell
param(
  [ValidateSet("base", "dev")]
  [string]$Overlay = "base"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$K8s = Join-Path $Root "infra\k8s"

Write-Host "==> Building images..."
docker build -t khalij/api-gateway:latest -f "$Root\services\api-gateway\Dockerfile" $Root
docker build -t khalij/data-ingestion:latest -f "$Root\services\data-ingestion\Dockerfile" $Root
docker build -t khalij/preprocessing:latest -f "$Root\services\preprocessing\Dockerfile" $Root
docker build -t khalij/prediction:latest -f "$Root\services\prediction\Dockerfile" $Root
docker build -t khalij/alerting:latest -f "$Root\services\alerting\Dockerfile" $Root

$secrets = Join-Path $K8s "base\secrets.yaml"
$example = Join-Path $K8s "base\secrets.example.yaml"
if (-not (Test-Path $secrets)) {
  Write-Host "==> Creating secrets.yaml from example"
  Copy-Item $example $secrets
}

$target = if ($Overlay -eq "dev") { Join-Path $K8s "overlays\dev" } else { Join-Path $K8s "base" }
Write-Host "==> Applying kustomize ($target)..."
kubectl apply -k $target

Write-Host "==> Status..."
kubectl -n khalij-pos get pods,svc,ingress,hpa
Write-Host "Done. Host: https://pos.khalij.local"
