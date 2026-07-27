# Runbook پایلوت — Khalij POS (فاز ۱۰)

## ۱. هدف پایلوت
اجرای ۱۴روزه روی **Olefin Unit 1** در حالت `shadow`/`assisted`: پیش‌بینی و توصیه فعال است؛ اعمال خودکار به DCS تا تأیید ایمنی ممنوع.

پیکربندی مرجع: [`config/pilot.yaml`](../../config/pilot.yaml)

## ۲. پیش از Go-Live (Gate)
```bash
python scripts/pilot_readiness.py
python scripts/test_phase10.py
```
موارد اجباری:
- [ ] رمزها و `JWT_SECRET_KEY` / `DATA_ENCRYPTION_KEY` / `INTERNAL_API_KEY` از مقادیر پیش‌فرض خارج شده‌اند
- [ ] 2FA برای اپراتورهای شیفت فعال و QR ثبت شده
- [ ] فایروال/VLAN بین OT و IT بررسی شده
- [ ] آموزش اپراتور اتاق کنترل انجام شده
- [ ] امضای سرپرست ایمنی (safety signoff)

## ۳. استقرار پایلوت

### Docker Compose
```bash
cp .env.example .env   # سپس مقادیر پایلوت را تنظیم کنید
docker compose -f docker-compose.yml -f docker-compose.pilot.yml up -d --build
curl http://localhost:8000/health/services
```

### Kubernetes
```bash
kubectl apply -k infra/k8s/overlays/pilot
kubectl -n khalij-pos get pods,svc,ingress
# Host: https://pilot.pos.khalij.local
```

### سوییچ به OPC-UA واقعی
در `.env` یا ConfigMap:
```
DATA_SOURCE_MODE=opcua
OPCUA_ENDPOINT_URL=opc.tcp://<dcs-host>:4840/...
```
سپس فقط `data-ingestion` را ریستارت کنید و Circuit Breaker را مانیتور کنید.

## ۴. عملیات روزانه
1. ورود داشبورد با 2FA → تب مانیتورینگ زنده
2. بررسی هشدارهای Critical در اتاق کنترل
3. اجرای What-if قبل از هر اعمال دستی توصیه
4. در پایان شیفت: تولید گزارش + خروجی PDF/Excel
5. بررسی `/observability/slo` و Grafana (در صورت فعال بودن)

## ۵. معیار موفقیت (خلاصه)
| AC | نیاز | آستانه |
|----|------|--------|
| AC-01 | نرخ داده | ≥ ۱ Hz |
| AC-02 | تأخیر پیش‌بینی P95 | ≤ ۲۰۰۰ ms |
| AC-03 | هشدار Critical | تحویل به اتاق کنترل |
| AC-04 | Optimize ایمن | constraints_satisfied |
| AC-05 | 2FA | اجباری |
| AC-06 | Uptime | downtime هفتگی ≤ ۶۰.۵ s |
| AC-07 | داشبورد | snapshot زنده |
| AC-08 | گزارش شیفت | export OK |

جزئیات: [`ACCEPTANCE.md`](ACCEPTANCE.md)

## ۶. Rollback (حداکثر ۳۰ دقیقه)
1. `DATA_SOURCE_MODE=simulator` یا قطع ingestion از DCS
2. Scale down prediction/alerting اگر نویز هشدار زیاد است
3. بازگردانی revision قبلی:
   ```bash
   kubectl -n khalij-pos rollout undo deployment/api-gateway
   kubectl -n khalij-pos rollout undo deployment/prediction
   ```
4. اعلام به اتاق کنترل و ثبت در audit / گزارش حادثه

## ۷. تماس اضطراری
| نقش | مسئولیت |
|-----|---------|
| سرپرست شیفت | تصمیم اعمال/توقف توصیه |
| مالک محصول AI | پایداری مدل و drift |
| OT/شبکه | ارتباط OPC-UA/Modbus |
| امنیت | 2FA / کلیدها / audit |

## ۸. خروج از پایلوت
- تکمیل گزارش [`REPORT_TEMPLATE.md`](REPORT_TEMPLATE.md)
- همه AC پاس یا با waiver مستند
- به‌روزرسانی runbook تولید و تصمیم Go/No-Go برای rollout گسترده‌تر
