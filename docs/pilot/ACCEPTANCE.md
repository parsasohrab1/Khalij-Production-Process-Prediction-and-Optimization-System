# چک‌لیست پذیرش پایلوت (UAT) — فاز ۱۰

منبع معیارها: `config/pilot.yaml` → `acceptance_criteria`

| ID | SRS | معیار | روش تأیید | نتیجه | امضا |
|----|-----|--------|-----------|--------|------|
| AC-01 | R-GEN-01 | ≥۱ رکورد/ثانیه | `GET /scale/ingestion` یا متریک ingestion | ☐ Pass ☐ Fail ☐ Waive | |
| AC-02 | FR-ML-01 / NFR-PER-01 | P95 پیش‌بینی ≤۲s | `GET /metrics/latency` | ☐ Pass ☐ Fail ☐ Waive | |
| AC-03 | FR-ML-02 | هشدار Critical به اتاق کنترل | تب اتاق کنترل / Redis alerts | ☐ Pass ☐ Fail ☐ Waive | |
| AC-04 | FR-ML-03 | Optimize با قیود ایمنی | `POST /optimize` → constraints_satisfied | ☐ Pass ☐ Fail ☐ Waive | |
| AC-05 | NFR-SEC-01 | ورود فقط با 2FA | `POST /auth/login` → requires_otp | ☐ Pass ☐ Fail ☐ Waive | |
| AC-06 | NFR-PER-02 | downtime ≤ بودجه SLO | Prometheus / `/observability/slo` | ☐ Pass ☐ Fail ☐ Waive | |
| AC-07 | R-GEN-03 | داشبورد زنده | `/dashboard` + WebSocket | ☐ Pass ☐ Fail ☐ Waive | |
| AC-08 | R-GEN-04 | گزارش شیفت PDF/Excel | `/reports/shift/export` | ☐ Pass ☐ Fail ☐ Waive | |

## سناریوهای کاربری اجباری
- [ ] اپراتور وارد می‌شود، OTP می‌زند، داشبورد را می‌بیند
- [ ] هشدار آزمایشی acknowledge می‌شود و در audit ثبت می‌گردد
- [ ] What-if قبل از apply اجرا می‌شود؛ apply فقط توسط supervisor+
- [ ] آموزش مدل دستی فقط توسط admin
- [ ] خروج (logout) توکن را باطل می‌کند

## ایمنی
- [ ] اعمال خودکار به DCS غیرفعال است (`auto_apply_setpoints` off)
- [ ] محدوده ایمن دما/فشار/دبی در توصیه نقض نمی‌شود
- [ ] مسیر Rollback در Runbook تمرین شده است

**تاریخ:** __________  **سایت:** __________  **تصمیم نهایی:** ☐ Go ☐ No-Go
