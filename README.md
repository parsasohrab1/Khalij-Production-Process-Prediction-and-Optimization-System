# Khalij-Production-Process-Prediction-and-Optimization-System
برای محصول **"سیستم پیش‌بینی‌کننده و بهینه‌ساز فرایند تولید"** در پتروشیمی، یک مستند **SRS (Software Requirements Specification)** جامع و سپس کد تولید **۱۰,۰۰۰ داده سنتتیک (شبیه‌سازی‌شده) به ازای هر متغیر** با زمان‌بندی ثانیه‌ای ارائه می‌شود.

---

## 🏗️ زیرساخت پیاده‌سازی‌شده (Implemented Infrastructure)

بر اساس معماری فنی بخش ۵ این سند، زیرساخت کامل پروژه به‌صورت مجموعه‌ای از میکروسرویس‌های FastAPI به همراه تمام سرویس‌های داده مورد نیاز (InfluxDB، PostgreSQL، Redis، Kafka، MLflow) و از طریق Docker Compose پیاده‌سازی شده است.

### نقشه معماری

```
                         ┌──────────────────┐
                         │   API Gateway     │  (JWT + 2FA - NFR-SEC-01)
                         │  (FastAPI, :8000)  │
                         └─────────┬─────────┘
                                   │
        ┌───────────────┬─────────┼─────────────┬───────────────┐
        │               │                       │               │
┌───────▼───────┐┌───────▼────────┐   ┌──────────▼───────┐┌──────▼──────┐
│Data Ingestion ││ Preprocessing  │   │    Prediction     ││  Alerting   │
│ OPC-UA/Modbus ││ Outlier/NaN/   │   │ LSTM/XGBoost +     ││ Telegram/   │
│ :8001         ││ Normalize:8002 │   │ Recommender :8003  ││ Email :8004 │
└──────┬────────┘└───────┬────────┘   └─────────┬─────────┘└──────┬──────┘
       │                 │                       │                │
       └────────────┬────┴───────────┬───────────┘                │
                     ▼                ▼                            ▼
              ┌────────────┐  ┌───────────────┐             ┌────────────┐
              │   Kafka    │  │   InfluxDB    │             │ PostgreSQL │
              │ (Streaming)│  │ (Time-Series) │             │(Transaction│
              └────────────┘  └───────────────┘             └────────────┘
                     │                                              │
              ┌────────────┐                               ┌────────────┐
              │   Redis    │                               │   MLflow   │
              │  (Cache)   │                               │  (MLOps)   │
              └────────────┘                               └────────────┘
```

جریان داده: `Data Ingestion` هر ثانیه یک رکورد سنسور (شبیه‌سازی‌شده یا از OPC-UA/Modbus) به Kafka (`raw-sensor-data`) و InfluxDB خام ارسال می‌کند → `Preprocessing` مصرف کرده، پرت‌ها را اصلاح، مقادیر گم‌شده را درون‌یابی و نرمال‌سازی می‌کند و در `processed-sensor-data` منتشر می‌کند → `Prediction` دمای ۶۰ ثانیه آینده را پیش‌بینی، در صورت انحراف بحرانی هشدار به `process-alerts` می‌فرستد و توصیه دبی خوراک بهینه را در PostgreSQL ثبت می‌کند → `Alerting` هشدارها را از طریق تلگرام/ایمیل ارسال، در PostgreSQL لاگ و برای نمایش در اتاق کنترل در Redis کش می‌کند.

### ساختار پوشه‌ها

| مسیر | توضیح |
| :--- | :--- |
| `shared/` | مدل‌های Pydantic، تنظیمات مشترک (`.env`)، ابزارهای Kafka |
| `services/api-gateway/` | دروازه واحد API، احراز هویت دو مرحله‌ای (NFR-SEC-01)، داشبورد `/dashboard` (R-GEN-03) |
| `services/data-ingestion/` | اتصال OPC-UA/Modbus، بافر محلی هنگام قطعی، Circuit Breaker (FR-DATA-01..03) |
| `services/preprocessing/` | حذف پرت، درون‌یابی، نرمال‌سازی (FR-PRE-01..03) |
| `services/prediction/` | پیش‌بینی دما با XGBoost/LSTM + توصیه‌گر تکاملی (FR-ML-01..03) |
| `services/alerting/` | تلگرام/ایمیل، لاگ هشدار، گزارش خودکار شیفت (FR-ALERT + R-GEN-04) |
| `infra/postgres/init.sql` | Schema اولیه PostgreSQL (اپراتورها، سنسورها، هشدارها، گزارش شیفت) |
| `infra/mlflow/` | Dockerfile سرور MLflow |
| `infra/nginx/` | Reverse proxy با TLS 1.3 (NFR-SEC-02) |
| `shared/schema_registry.py` | Schema Registry سبک (فاز ۲) |
| `shared/dlq.py` | ناشر Dead Letter Queue (فاز ۲) |
| `shared/data_quality.py` | Expectation Suite کیفیت داده (فاز ۲) |
| `infra/influxdb/` | Init bucket cold + Task downsampling |
| `data/generate_synthetic_data.py` | تولید ۱۰,۰۰۰ رکورد داده سنتتیک برای هر متغیر |
| `scripts/test_phase1.py` … `test_phase10.py` | تست‌های واحد فاز ۱ تا ۱۰ |
| `config/pilot.yaml` / `docs/pilot/` | پیکربندی و Runbook پایلوت (فاز ۱۰) |
| `docker-compose.pilot.yml` | پروفایل Compose پایلوت |
| `infra/k8s/` | مانیفست‌های Kubernetes + overlays dev/pilot |
| `docker-compose.yml` | زیرساخت کامل (+ `hardware-sim`, `kafka-init`, `influxdb-init`) |

### راه‌اندازی سریع (Quick Start)

```bash
# ۱. کپی فایل نمونه متغیرهای محیطی و ویرایش مقادیر حساس
cp .env.example .env

# ۲. بالا آوردن کامل زیرساخت
docker compose up --build -d

# ۳. بررسی سلامت سرویس‌ها
curl http://localhost:8000/health/services
```

سرویس `data-ingestion` به‌صورت پیش‌فرض با یک شبیه‌ساز داخلی (`DATA_SOURCE_MODE=simulator`) کار می‌کند تا بدون نیاز به سخت‌افزار واقعی OPC-UA/Modbus، کل خط لوله (Ingestion → Kafka → Preprocessing → Prediction → Alerting) قابل تست باشد.

برای ورود به داشبورد (اپراتور دمو، رمز پیش‌فرض `ChangeMe123!`):

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"employee_code": "demo-admin", "password": "ChangeMe123!"}'
# پاسخ شامل pending_token است؛ کد OTP را با ابزاری مانند Google Authenticator
# روی رمز Base32 موجود در جدول operators (ستون otp_secret) تولید کنید.
curl -X POST http://localhost:8000/auth/verify-otp \
  -H "Content-Type: application/json" \
  -d '{"pending_token": "<pending_token>", "otp_code": "<کد ۶ رقمی>"}'
```

⚠️ رمز عبور و راز OTP اپراتور دمو صرفاً برای محیط توسعه است؛ پیش از استقرار عملیاتی حذف/تغییر داده شود.

### تولید داده سنتتیک برای تست/آموزش مدل

```bash
pip install -r data/requirements.txt
python data/generate_synthetic_data.py --num-records 10000
```

### متغیرهای محیطی کلیدی

فایل `.env.example` تمام متغیرهای مورد نیاز (اتصال InfluxDB/PostgreSQL/Redis/Kafka/MLflow، آستانه‌های هشدار، تنظیمات تلگرام/SMTP، کلید JWT و کلید AES-256) را با توضیح فارسی شامل می‌شود.

### داشبورد مانیتورینگ (R-GEN-03 / فاز ۵)

پس از بالا آوردن سرویس‌ها:

- HTTP: [http://localhost:8000/dashboard](http://localhost:8000/dashboard)
- HTTPS با TLS 1.3: [https://localhost/dashboard](https://localhost/dashboard)

ورود با اپراتور دمو + OTP (NFR-SEC-01). داشبورد شامل تب‌های مانیتورینگ زنده (WebSocket)، اتاق کنترل، بهینه‌سازی، گزارش شیفت (PDF/Excel) و ثبت QR برای 2FA است.

### تست اتصال سخت‌افزاری (فاز ۱ / FR-DATA-01)

```bash
# بالا آوردن شبیه‌ساز OPC-UA/Modbus + بقیه سرویس‌ها
docker compose --profile hardware-sim up --build -d

# سوییچ data-ingestion به OPC-UA (در .env)
# DATA_SOURCE_MODE=opcua
docker compose up -d data-ingestion

# یا تست واحدهای فاز ۱ بدون Docker
pip install cryptography PyYAML
python scripts/test_phase1.py
```

### فاز ۲ — خط لوله داده و کیفیت داده

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| Schema Registry | `shared/schema_registry.py` — اعتبارسنجی Pydantic + نسخه‌بندی |
| Dead Letter Queue | topicهای `raw-sensor-data-dlq` و `processed-sensor-data-dlq` |
| Retention / Downsampling | bucket hot=`30d` + cold=`process_sensors_1m` با retention ۵ ساله؛ Task هر ۱ دقیقه |
| Data Quality | `shared/data_quality.py` + CLI در `services/data-quality/cli.py` |

```bash
# تست واحد فاز ۲
python scripts/test_phase2.py

# اجرای Expectation Suite روی CSV سنتتیک
python data/generate_synthetic_data.py --num-records 1000 --output data/sample.csv
pip install -r services/data-quality/requirements.txt
python -m services.data_quality.cli --csv data/sample.csv --limit 1000

# آمار کیفیت از API (پس از login)
curl -H "Authorization: Bearer <token>" http://localhost:8000/quality/stats
```

### فاز ۳ — مدل‌سازی و MLOps واقعی

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| Batch training + backtesting | `training_pipeline.py` — تقسیم زمانی، MAE/RMSE/MAPE |
| مقایسه مدل‌ها | XGBoost vs MLP (و LSTM در صورت نصب TensorFlow) |
| MLflow Registry | Experiment + Staging → Production |
| Drift Detection | PSI روی دمای راکتور → Re-training خودکار |

```bash
# تست واحد فاز ۳
python scripts/test_phase3.py

# آموزش آفلاین از CSV
python data/generate_synthetic_data.py --num-records 5000 --output data/train.csv
python scripts/train_model.py --csv data/train.csv --mlflow-uri http://localhost:5000

# APIها
curl -X POST http://localhost:8003/train
curl http://localhost:8003/models/comparison
curl -X POST http://localhost:8003/drift/check
```

### فاز ۴ — بهینه‌سازی پیشرفته و محدودیت‌های ایمنی

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| بهینه‌سازی چندمتغیره | دبی خوراک + فشار هم‌زمان (`MultiVariableEvolutionaryOptimizer`) |
| Hard Constraints | محدوده ایمن، نرخ تغییر، قید ترکیبی P+T (`safety_constraints.py`) |
| What-if | شبیه‌سازی پیش از اعمال (`/optimize/whatif`) |
| حلقه بسته | اعمال توصیه → ثبت راندمان واقعی → خطای پیش‌بینی |

```bash
python scripts/test_phase4.py

# بهینه‌سازی چندمتغیره
curl -X POST http://localhost:8003/optimize \
  -H "Content-Type: application/json" \
  -d '{"reactor_temp_c":250,"pressure_bar":28,"feed_flow_m3h":380}'

# What-if
curl -X POST http://localhost:8003/optimize/whatif \
  -H "Content-Type: application/json" \
  -d '{"reactor_temp_c":250,"current_pressure_bar":28,"current_feed_flow":380,"proposed_pressure_bar":25,"proposed_feed_flow":320}'

# اعمال + بازخورد
curl -X POST http://localhost:8003/optimize/apply -H "Content-Type: application/json" \
  -d '{"recommendation_id":1,"operator_id":1}'
curl -X POST http://localhost:8003/optimize/feedback -H "Content-Type: application/json" \
  -d '{"recommendation_id":1,"actual_efficiency":72.5}'
```

### فاز ۵ — داشبورد و تجربه کاربری اپراتور

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| WebSocket زنده | `GET/WS /ws/live?token=...` — سنسور، پیش‌بینی، توصیه، هشدار |
| داشبورد چندصفحه‌ای | مانیتورینگ / اتاق کنترل / بهینه‌سازی / گزارش / امنیت 2FA |
| ثبت TOTP با QR | `POST /auth/totp/setup` + تصویر PNG Base64 |
| خروجی گزارش شیفت | `GET /reports/shift/export?format=pdf\|xlsx` (R-GEN-04) |

```bash
# تست واحد فاز ۵
pip install qrcode[pil] openpyxl reportlab pyotp python-jose
python scripts/test_phase5.py

# داشبورد
# http://localhost:8000/dashboard

# WebSocket (پس از login)
# ws://localhost:8000/ws/live?token=<access_token>&unit_id=1

# QR برای Authenticator
curl -X POST http://localhost:8000/auth/totp/setup \
  -H "Content-Type: application/json" \
  -d '{"employee_code":"demo-admin","password":"ChangeMe123!"}'

# خروجی Excel / PDF گزارش شیفت
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/reports/shift/export?format=xlsx" -o shift.xlsx
curl -H "Authorization: Bearer <token>" \
  "http://localhost:8000/reports/shift/export?format=pdf" -o shift.pdf
```

### فاز ۶ — امنیت و سخت‌سازی

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| RBAC | `operator` < `supervisor` < `admin` — apply/export/train محدود شده |
| قفل حساب | پس از ۵ ورود ناموفق، ۹۰۰ث قفل (`LOGIN_*`) |
| Rate limit | Redis روی login/API + `limit_req` در nginx |
| Audit trail | جدول `audit_events` + `GET /security/audit` (admin) |
| Logout / ابطال توکن | `POST /auth/logout` + blacklist jti در Redis |
| سیاست رمز | `POST /auth/change-password` + قوانین پیچیدگی |
| هدرهای امنیتی | CSP / HSTS / X-Frame-Options در Gateway و nginx |
| CORS محدود | `CORS_ALLOW_ORIGINS` |
| کلید داخلی سرویس‌ها | `INTERNAL_API_KEY` → هدر `X-Internal-Api-Key` |
| Secrets در production | `ENFORCE_PRODUCTION_SECRETS` / `ENVIRONMENT=production` |

```bash
python scripts/test_phase6.py

# وضعیت امنیتی (admin)
curl -H "Authorization: Bearer <token>" http://localhost:8000/security/status

# لاگ audit
curl -H "Authorization: Bearer <token>" http://localhost:8000/security/audit?limit=20
```

نقش‌های دمو (رمز `ChangeMe123!` + همان OTP secret): `demo-admin` / `demo-supervisor` / `demo-operator`

### فاز ۷ — مقیاس‌پذیری و کارایی

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| شاردینگ واحدها | `DATA_UNIT_IDS` + `INGESTION_SHARD_COUNT` / `SHARD_ID` |
| Kafka پرتوان | compression lz4، linger/batch، پارتیشن پیش‌فرض ۱۲ |
| Influx batch | `InfluxRawWriter.write_batch` + async WriteOptions |
| بک‌پرشر | توقف موقت ingestion وقتی بافر محلی پر است |
| بودجه تأخیر | `LatencyTracker` + `/metrics/latency` (NFR-PER-01 <۲ث) |
| Liveness/Readiness | `/health/live` و `/health/ready` روی سرویس‌ها |
| Scale compose | `docker-compose.scale.yml` |

```bash
python scripts/test_phase7.py
python scripts/load_test_scale.py --units 1000 --seconds 3

# مقیاس افقی (مثال ۳ ingestion + ۲ preprocessing + ۲ prediction)
docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d \
  --scale data-ingestion=3 --scale preprocessing=2 --scale prediction=2

# متریک تأخیر پیش‌بینی
curl -H "Authorization: Bearer <token>" http://localhost:8000/metrics/latency
```

برای نزدیک شدن به هدف ۵۰٬۰۰۰ سنسور: `DATA_UNIT_IDS=1-50000`، افزایش `KAFKA_PARTITIONS`، و scale روی ingestion/preprocessing/prediction.

### فاز ۸ — مشاهده‌پذیری و Uptime (NFR-PER-02)

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| Prometheus metrics | `/metrics` روی همه سرویس‌ها + `shared/metrics.py` |
| Grafana dashboard | `infra/observability/grafana/dashboards/khalij-pos-overview.json` |
| Loki + Promtail | جمع‌آوری لاگ JSON کانتینرها |
| Tempo (OTLP) | tracing توزیع‌شده با `OTEL_EXPORTER_OTLP_ENDPOINT` |
| Alert rules | ServiceDown / HighErrorRate / HighPredictionLatency / ErrorBudgetBurn |
| SLO helper | `shared/slo.py` + `GET /observability/slo` |

```bash
pip install prometheus-client httpx
python scripts/test_phase8.py

# استک مشاهده‌پذیری
docker compose -f docker-compose.yml -f docker-compose.observability.yml --profile observability up -d

# UI
# Grafana    http://localhost:3000  (admin/admin)
# Prometheus http://localhost:9090
# Tempo      http://localhost:3200

curl -H "Authorization: Bearer <token>" http://localhost:8000/observability/status
curl -H "Authorization: Bearer <token>" "http://localhost:8000/observability/slo?downtime_seconds=30"
```

بودجه خطای هفتگی ۹۹.۹۹٪ حدود **۶۰.۵ ثانیه** downtime است؛ هشدار `ServiceDown` پس از ۱ دقیقه قطعی فعال می‌شود.

### فاز ۹ — استقرار Kubernetes

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| Kustomize | `infra/k8s/base` + overlay `dev` |
| Apps | Deployment/Service/PDB برای ۵ میکروسرویس |
| Infra | Postgres / Redis / Kafka / InfluxDB |
| Probes | `/health/live` + `/health/ready` |
| HPA | مقیاس خودکار روی CPU |
| Ingress + TLS | `pos.khalij.local` + NetworkPolicy |
| Observability | Prometheus با kubernetes pod SD |
| Deploy | `scripts/deploy-k8s.sh` / `.ps1` |

```bash
pip install PyYAML
python scripts/test_phase9.py

# استقرار (نیاز به کلاستر + docker)
./scripts/deploy-k8s.sh dev
# یا
.\scripts\deploy-k8s.ps1 -Overlay dev

kubectl apply -k infra/k8s/base
kubectl -n khalij-pos get pods,svc,ingress,hpa
```

جزئیات: [`infra/k8s/README.md`](infra/k8s/README.md)

### فاز ۱۰ — پایلوت عملیاتی (Olefin Unit 1)

| قابلیت | پیاده‌سازی |
| :--- | :--- |
| پیکربندی پایلوت | `config/pilot.yaml` (حالت shadow/assisted، ACها) |
| Compose پایلوت | `docker-compose.pilot.yml` |
| K8s overlay | `infra/k8s/overlays/pilot` → host `pilot.pos.khalij.local` |
| Runbook / UAT | `docs/pilot/RUNBOOK.md`, `ACCEPTANCE.md`, `REPORT_TEMPLATE.md` |
| Readiness gate | `scripts/pilot_readiness.py` |
| Smoke test | `scripts/pilot_smoke.py` (--offline یا --base-url) |

```bash
pip install PyYAML
python scripts/test_phase10.py
python scripts/pilot_readiness.py
python scripts/pilot_smoke.py --offline

# استقرار پایلوت محلی
docker compose -f docker-compose.yml -f docker-compose.pilot.yml up -d --build
python scripts/pilot_smoke.py --base-url http://localhost:8000

# Kubernetes
kubectl apply -k infra/k8s/overlays/pilot
```

اعمال خودکار به DCS تا امضای ایمنی **غیرفعال** است (`auto_apply_setpoints`).

### ماتریس پوشش نیازمندی‌های SRS

| شناسه | نیاز | وضعیت پیاده‌سازی |
| :--- | :--- | :--- |
| R-GEN-01 | دریافت ۱ رکورد/ثانیه | ✅ `data-ingestion` + AC-01 پایلوت |
| R-GEN-02 | Data Lake پنج‌ساله | ✅ InfluxDB retention=`1825d` |
| R-GEN-03 | داشبورد مانیتورینگ + هشدارها | ✅ `/dashboard` + AC-07 |
| R-GEN-04 | گزارش خودکار انرژی پایان شیفت | ✅ PDF/Excel + AC-08 |
| FR-DATA-01 | OPC-UA / Modbus | ✅ کلاینت + `hardware_sim` + Circuit Breaker |
| FR-DATA-02 | T/P/F/L/GC/RPM | ✅ نگاشت تگ و مدل داده |
| FR-DATA-03 | بافر محلی هنگام قطعی | ✅ `LocalBuffer` + Fallback |
| FR-PRE-01 | حذف پرت (IQR/Z-Score) | ✅ `preprocessing` |
| FR-PRE-02 | درون‌یابی خطی NaN | ✅ `preprocessing` |
| FR-PRE-03 | نرمال‌سازی Min-Max | ✅ `preprocessing` |
| FR-ML-01 | پیش‌بینی دما ۶۰ثانیه (LSTM/XGBoost) | ✅ + AC-02 پایلوت |
| FR-ML-02 | هشدار Critical در انحراف >۵٪ | ✅ + AC-03 |
| FR-ML-03 | توصیه‌گر تکاملی دبی خوراک | ✅ + AC-04 (بدون auto-apply) |
| FR-ALERT-01 | تلگرام / ایمیل / اتاق کنترل | ✅ `alerting` + Redis |
| FR-ALERT-02 | لاگ هشدار + اپراتور پاسخ‌دهنده | ✅ PostgreSQL `alerts` |
| NFR-SEC-01 | احراز هویت دو مرحله‌ای | ✅ + AC-05 |
| NFR-SEC-02 | AES-256 / TLS 1.3 | ✅ crypto + tls-gateway + Ingress |
| NFR-PER-01 | زمان پاسخ پیش‌بینی <۲ث | ✅ LatencyTracker + AC-02 |
| NFR-SCL-01 | مقیاس افقی تا ۵۰k سنسور | ✅ شاردینگ + HPA |
| NFR-PER-02 | Uptime ۹۹.۹۹٪ | ✅ SLO + AC-06 + پایلوت ۱۴روزه |

---

## 📄 مستند SRS – سیستم بهینه‌سازی فرایند تولید (POS)

### ۱. مقدمه (Introduction)
**هدف:** توسعه سیستمی مبتنی بر داده‌کاوی و یادگیری ماشین برای پیش‌بینی ناهنجاری‌های فرایندی و ارائه تنظیمات بهینه به اپراتورها به‌منظور کاهش مصرف انرژی و افزایش راندمان واکنش‌های شیمیایی.

**دامنه:** این سیستم روی واحدهای الفین و پلیمریزاسیون هلدینگ پیاده‌سازی شده و به سیستم DCS (کنترل توزیع‌شده) متصل می‌شود.

### ۲. نیازمندی‌های کلی (General Requirements)
| شناسه | نیاز | اولویت |
| :--- | :--- | :--- |
| R-GEN-01 | دریافت داده‌های لحظه‌ای از سنسورها با نرخ حداقل ۱ رکورد در ثانیه | بالا |
| R-GEN-02 | ذخیره‌سازی داده‌های خام در دیتاﻻیک (Data Lake) به مدت ۵ سال | بالا |
| R-GEN-03 | ارائه داشبورد مانیتورینگ با قابلیت نمایش هشدارهای پیش‌بینی‌شده | بالا |
| R-GEN-04 | تولید خودکار گزارش بهینه‌سازی انرژی در پایان هر شیفت | متوسط |

### ۳. نیازمندی‌های عملکردی (Functional Requirements)

#### ۳-۱. ماژول جمع‌آوری داده (Data Ingestion)
- **FR-DATA-01:** سیستم باید قادر به اتصال به پروتکل‌های OPC-UA یا Modbus برای دریافت داده از سنسورها باشد.
- **FR-DATA-02:** داده‌های دریافتی شامل: دما (T)، فشار (P)، دبی جریان (F)، سطح مخزن (L)، ترکیب گاز خروجی (GC) و دور کمپرسور (RPM) باشد.
- **FR-DATA-03:** در صورت قطع ارتباط، داده‌ها در بافر محلی ذخیره و پس از وصل مجدد ارسال شوند.

#### ۳-۲. ماژول پیش‌پردازش (Preprocessing)
- **FR-PRE-01:** تشخیص و حذف داده‌های پرت (Outlier) با استفاده از روش IQR یا Z-Score.
- **FR-PRE-02:** درون‌یابی (Interpolation) خطی برای جایگزینی مقادیر ازدست‌رفته (NaN).
- **FR-PRE-03:** نرمال‌سازی داده‌ها با روش Min-Max یا StandardScaler برای ورود به مدل.

#### ۳-۳. ماژول پیش‌بینی و بهینه‌سازی (Prediction & Optimization)
- **FR-ML-01:** پیش‌بینی دمای خروجی راکتور (Target Variable) برای ۶۰ ثانیه آینده با استفاده از مدل LSTM یا XGBoost.
- **FR-ML-02:** در صورت پیش‌بینی انحراف بیش از ۵٪ از دمای نامی، هشدار سطح بحرانی (Critical) صادر شود.
- **FR-ML-03:** سیستم توصیه‌گر (Recommender) با استفاده از الگوریتم‌های تکاملی، مقدار بهینه دبی خوراک ورودی را برای رسیدن به بیشینه راندمان محاسبه کند.

#### ۳-۴. ماژول گزارش و هشدار (Alerting)
- **FR-ALERT-01:** ارسال هشدار از طریق تلگرام، ایمیل و نمایش روی صفحه کنترل اتاق مرکزی.
- **FR-ALERT-02:** ثبت لاگ کلیه هشدارها با زمان دقیق و شناسه اپراتور پاسخ‌دهنده.

### ۴. نیازمندی‌های غیرعملکردی (Non-Functional Requirements)

| شناسه | نیاز | مقدار هدف |
| :--- | :--- | :--- |
| NFR-PER-01 | زمان پاسخ‌دهی پیش‌بینی | کمتر از ۲ ثانیه |
| NFR-PER-02 | در دسترس بودن (Uptime) | ۹۹.۹۹٪ (کمتر از ۱ دقیقه توقف در هفته) |
| NFR-SEC-01 | احراز هویت دو مرحله‌ای (2FA) برای دسترسی به تنظیمات | اجباری |
| NFR-SEC-02 | رمزنگاری داده‌ها در حالت ذخیره‌سازی (AES-256) و انتقال (TLS 1.3) | اجباری |
| NFR-SCL-01 | قابلیت مقیاس‌پذیری افقی برای پشتیبانی از ۵۰,۰۰۰ سنسور | مورد انتظار |

### ۵. معماری فنی (Technical Architecture)
- **زبان برنامه‌نویسی:** Python 3.10
- **چارچوب وب:** FastAPI (برای microservices)
- **پایگاه داده:** InfluxDB (برای داده‌های سری زمانی) + PostgreSQL (برای داده‌های تراکنشی)
- **کش (Cache):** Redis
- **ارسال پیام:** Apache Kafka (برای استریمینگ داده)
- **MLOps:** MLflow برای ثبت مدل‌ها

---

## 🧪 کد تولید داده‌های سنتتیک (Synthetic Data Generator)

> 📌 نسخه اجراشدنی و به‌روز این کد در فایل [`data/generate_synthetic_data.py`](data/generate_synthetic_data.py) قرار دارد (قابل اجرا با `python data/generate_synthetic_data.py`). کد زیر صرفاً برای مرجع مستندسازی نگه‌داشته شده است.

کد زیر در پایتون نوشته شده و **۱۰,۰۰۰ رکورد** برای هر یک از **۷ متغیر کلیدی** با نرخ **۱ رکورد در ثانیه** تولید می‌کند. داده‌ها شامل الگوهای سینوسی، روندهای فصلی و نویز گاوسی برای شبیه‌سازی دنیای واقعی هستند و در نهایت در یک فایل CSV ذخیره می‌شوند.

```python
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# ==============================================
# پارامترهای تولید داده
# ==============================================
NUM_RECORDS = 10000          # تعداد رکوردها برای هر متغیر (تقریباً 2.7 ساعت داده)
START_TIME = datetime(2026, 7, 22, 8, 0, 0)   # زمان شروع (مشابه امروز)

# ==============================================
# تولید برچسب زمانی با فاصله 1 ثانیه
# ==============================================
timestamps = [START_TIME + timedelta(seconds=i) for i in range(NUM_RECORDS)]

# ==============================================
# تولید داده‌های سنتتیک برای هر سنسور
# ==============================================

# 1. دمای راکتور (Reactor Temperature) - محدوده 150 تا 350 درجه سانتی‌گراد
# شامل یک روند افزایشی و نوسان سیکلی
t = np.linspace(0, 20 * np.pi, NUM_RECORDS)
reactor_temp = 250 + 30 * np.sin(t * 0.5) + 0.01 * np.arange(NUM_RECORDS) + np.random.normal(0, 2, NUM_RECORDS)
reactor_temp = np.clip(reactor_temp, 150, 350)

# 2. فشار راکتور (Reactor Pressure) - محدوده 10 تا 40 بار
pressure = 25 + 5 * np.sin(t * 0.3) + 0.005 * np.arange(NUM_RECORDS) + np.random.normal(0, 0.8, NUM_RECORDS)
pressure = np.clip(pressure, 10, 40)

# 3. دبی جریان خوراک ورودی (Feed Flow) - محدوده 100 تا 500 مترمکعب بر ساعت
feed_flow = 300 + 80 * np.sin(t * 0.2 + 1.2) + np.random.normal(0, 5, NUM_RECORDS)
feed_flow = np.clip(feed_flow, 100, 500)

# 4. سطح مخزن (Tank Level) - محدوده 20 تا 85 درصد
tank_level = 50 + 20 * np.sin(t * 0.15 + 2.5) + np.random.normal(0, 1.5, NUM_RECORDS)
tank_level = np.clip(tank_level, 20, 85)

# 5. ترکیب گاز خروجی (Ethylene Concentration) - محدوده 12 تا 25 درصد
ethylene_conc = 18 + 3 * np.sin(t * 0.25 + 0.8) + 0.002 * np.arange(NUM_RECORDS) + np.random.normal(0, 0.5, NUM_RECORDS)
ethylene_conc = np.clip(ethylene_conc, 12, 25)

# 6. دور کمپرسور (Compressor RPM) - محدوده 1200 تا 1800 دور بر دقیقه
compressor_rpm = 1500 + 150 * np.sin(t * 0.1 + 3.0) + np.random.normal(0, 10, NUM_RECORDS)
compressor_rpm = np.clip(compressor_rpm, 1200, 1800)

# 7. راندمان تولید (Production Efficiency) - متغیر هدف (بر اساس سایر متغیرها)
# شبیه‌سازی راندمان به عنوان تابعی از دما و فشار (با نویز)
efficiency = ( (reactor_temp - 200) / 150 * 20 + (pressure - 20) / 20 * 10 + 60 
               + np.random.normal(0, 2, NUM_RECORDS) )
efficiency = np.clip(efficiency, 40, 98)

# ==============================================
# ساخت دیتافریم
# ==============================================
df = pd.DataFrame({
    'timestamp': timestamps,
    'reactor_temp_c': np.round(reactor_temp, 2),
    'reactor_pressure_bar': np.round(pressure, 2),
    'feed_flow_m3h': np.round(feed_flow, 2),
    'tank_level_percent': np.round(tank_level, 2),
    'ethylene_conc_percent': np.round(ethylene_conc, 2),
    'compressor_rpm': np.round(compressor_rpm, 0).astype(int),
    'efficiency_target': np.round(efficiency, 2)   # متغیر وابسته (هدف)
})

# ==============================================
# ذخیره در فایل CSV
# ==============================================
output_file = "petrochemical_sensor_data_10k.csv"
df.to_csv(output_file, index=False)
print(f"✅ داده‌های سنتتیک با موفقیت در فایل '{output_file}' ذخیره شدند.")
print(f"📊 تعداد رکوردها: {len(df):,} - تعداد متغیرها: {len(df.columns)}")

# نمایش ۵ رکورد اول
print("\n🔍 نمونه داده‌های تولید شده:")
print(df.head())

# نمایش اطلاعات آماری خلاصه
print("\n📈 آمار توصیفی داده‌ها:")
print(df.describe())
```

---

### 📊 خروجی نمونه (نمایش ۵ رکورد اول):

| timestamp | reactor_temp_c | reactor_pressure_bar | feed_flow_m3h | tank_level_percent | ethylene_conc_percent | compressor_rpm | efficiency_target |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 2026-07-22 08:00:00 | 250.12 | 24.85 | 301.45 | 49.83 | 18.12 | 1502 | 68.45 |
| 2026-07-22 08:00:01 | 250.45 | 24.92 | 302.11 | 50.01 | 18.08 | 1505 | 68.92 |
| ... | ... | ... | ... | ... | ... | ... | ... |

---

### 🔧 نکات فنی پیاده‌سازی کد:
1.  **نرخ نمونه‌برداری:** `timedelta(seconds=i)` تضمین می‌کند که دقیقاً ۱ رکورد در ثانیه داشته باشید.
2.  **نویز واقع‌گرایانه:** از توزیع نرمال (`np.random.normal`) برای شبیه‌سازی خطای سنسور استفاده شده است.
3.  **دامنه منطقی:** تمام مقادیر با `np.clip` در محدوده فیزیکی مجاز سنسورها نگهداری می‌شوند.
4.  **رابطه علّی:** متغیر `efficiency_target` به‌عنوان تابعی غیرخطی از دما و فشار طراحی شده تا مدل یادگیری ماشین بتواند الگو را کشف کند.




📄 مستند SRS – محصول ۱: بهینه‌سازی فرایندهای تولید و عملیات (با قابلیت ثبت اختراع)
۱. مقدمه
هدف: توسعه سیستمی مبتنی بر داده‌کاوی و یادگیری ماشین برای پیش‌بینی ناهنجاری‌های فرایندی و ارائه تنظیمات بهینه به اپراتورها به‌منظور کاهش مصرف انرژی، افزایش راندمان واکنش‌های شیمیایی و کاهش تولید محصولات نامنطبق (Off-Spec) .

نوآوری ثبت اختراع: برخلاف اختراع پتروشیمی جم که صرفاً بر پیش‌بینی خواص محصول متمرکز است ، این سیستم قابلیت "بهینه‌سازی هم‌زمان سه هدف متضاد (هزینه تولید، کیفیت محصول، مصرف انرژی)" را با استفاده از الگوریتم‌های فراابتکاری و تولید داده‌های مصنوعی برای آموزش مدل در شرایط کم‌داده ارائه می‌دهد.

۲. نیازمندی‌های عملکردی (با تأکید بر قابلیت‌های اختراع)
شناسه	نیاز	قابلیت ثبت اختراع
FR-ML-01	پیش‌بینی بلادرنگ پارامترهای کیفی محصول (MFI، چگالی، اندازه ذرات) با استفاده از حسگرهای مجازی مبتنی بر یادگیری ماشین 	حسگرهای مجازی هوشمند (مشابه اختراع ۱۱۲۰۵۷)
FR-ML-02	پیش‌بینی دمای خروجی راکتور و سایر متغیرهای فرایندی برای ۶۰ ثانیه آینده با مدل LSTM یا XGBoost	پیش‌بینی چندمتغیره هم‌زمان
FR-OPT-01	بهینه‌سازی هم‌زمان سه هدف هزینه، کیفیت و مصرف انرژی با الگوریتم ازدحام ذرات (PSO) و تعیین جبهه پارتو	بهینه‌سازی چندهدفه (نوآوری اصلی)
FR-OPT-02	تولید داده‌های سنتتیک با روش‌های مونت کارلو و GAN برای آموزش مدل در شرایط کم‌داده تاریخی	تولید داده مجازی (نوآوری جدید)
FR-ALERT-01	ارسال هشدار پیش‌بینی‌شده به اپراتور و ارائه توصیه‌های عملیاتی برای تنظیم پارامترها	سیستم توصیه‌گر بلادرنگ
