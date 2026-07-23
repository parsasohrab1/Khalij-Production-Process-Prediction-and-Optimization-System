-- ==========================================================================
-- Khalij POS - Schema اولیه PostgreSQL (داده‌های تراکنشی)
-- مطابق R-GEN-02، FR-ALERT-02، R-GEN-04 سند SRS
-- ==========================================================================

-- پایگاه داده جداگانه برای MLflow (ثبت مدل‌ها) تا از داده تراکنشی جدا باشد
SELECT 'CREATE DATABASE mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')
\gexec

-- ---------------------------------------------------------------------
-- اپراتورها و کاربران سیستم
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operators (
    id              SERIAL PRIMARY KEY,
    employee_code   VARCHAR(32) UNIQUE NOT NULL,
    full_name       VARCHAR(128) NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    otp_secret      VARCHAR(64),                               -- Base32 secret برای TOTP (NFR-SEC-01)
    role            VARCHAR(32) NOT NULL DEFAULT 'operator', -- operator | supervisor | admin
    shift           VARCHAR(16),                              -- morning | evening | night
    two_factor_enabled BOOLEAN NOT NULL DEFAULT TRUE,          -- NFR-SEC-01
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- تعریف واحدها و سنسورها (الفین / پلیمریزاسیون)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS units (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(64) NOT NULL,       -- e.g. Olefin Unit 1
    unit_type       VARCHAR(32) NOT NULL,       -- olefin | polymerization
    description     TEXT
);

CREATE TABLE IF NOT EXISTS sensors (
    id              SERIAL PRIMARY KEY,
    unit_id         INTEGER REFERENCES units(id) ON DELETE CASCADE,
    tag             VARCHAR(64) UNIQUE NOT NULL, -- e.g. reactor_temp_c
    variable_name   VARCHAR(64) NOT NULL,        -- Temperature | Pressure | Flow | Level | GasComposition | RPM
    unit_of_measure VARCHAR(16),
    protocol        VARCHAR(16) NOT NULL DEFAULT 'OPC-UA', -- OPC-UA | Modbus
    min_value       DOUBLE PRECISION,
    max_value       DOUBLE PRECISION,
    nominal_value   DOUBLE PRECISION,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE
);

-- ---------------------------------------------------------------------
-- هشدارها (FR-ALERT-01 / FR-ALERT-02)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS alerts (
    id                  BIGSERIAL PRIMARY KEY,
    sensor_id           INTEGER REFERENCES sensors(id),
    level               VARCHAR(16) NOT NULL,        -- info | warning | critical
    message             TEXT NOT NULL,
    predicted_value     DOUBLE PRECISION,
    nominal_value       DOUBLE PRECISION,
    deviation_percent    DOUBLE PRECISION,
    channel_telegram_sent BOOLEAN NOT NULL DEFAULT FALSE,
    channel_email_sent    BOOLEAN NOT NULL DEFAULT FALSE,
    raised_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at     TIMESTAMPTZ,
    acknowledged_by     INTEGER REFERENCES operators(id)
);

CREATE INDEX IF NOT EXISTS idx_alerts_raised_at ON alerts (raised_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_level ON alerts (level);

-- ---------------------------------------------------------------------
-- گزارش بهینه‌سازی انرژی پایان شیفت (R-GEN-04)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shift_reports (
    id                  BIGSERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id),
    shift               VARCHAR(16) NOT NULL,
    shift_start         TIMESTAMPTZ NOT NULL,
    shift_end           TIMESTAMPTZ NOT NULL,
    avg_efficiency      DOUBLE PRECISION,
    energy_saved_kwh    DOUBLE PRECISION,
    recommendation_summary TEXT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- توصیه‌های بهینه‌سازی صادر شده توسط ماژول Recommender (FR-ML-03)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS optimization_recommendations (
    id                  BIGSERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id),
    variable_name       VARCHAR(64) NOT NULL,
    current_value       DOUBLE PRECISION,
    recommended_value   DOUBLE PRECISION,
    expected_efficiency_gain DOUBLE PRECISION,
    model_run_id        VARCHAR(64), -- MLflow run id
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied              BOOLEAN NOT NULL DEFAULT FALSE,
    applied_by           INTEGER REFERENCES operators(id)
);

-- ---------------------------------------------------------------------
-- اپراتور دمو برای تست ورود (NFR-SEC-01) - رمز عبور پیش‌فرض: ChangeMe123!
-- ⚠️ حتماً پس از استقرار در محیط عملیاتی این رکورد را حذف/به‌روزرسانی کنید.
-- ---------------------------------------------------------------------
INSERT INTO operators (employee_code, full_name, password_hash, otp_secret, role, shift)
VALUES (
    'demo-admin',
    'اپراتور دمو',
    '$2b$12$dTFM.AIRyaHlm8xioKQLnegLWMo1PT8AwDuuZHNO6SWHTD5QFUyyS',
    '3MYXLVCKBIRJUTD6',
    'admin',
    'morning'
)
ON CONFLICT (employee_code) DO NOTHING;

-- ---------------------------------------------------------------------
-- داده اولیه نمونه (واحد و سنسورهای پیش‌فرض بر اساس FR-DATA-02)
-- ---------------------------------------------------------------------
INSERT INTO units (name, unit_type, description)
VALUES ('Olefin Unit 1', 'olefin', 'واحد الفین شماره ۱ - راکتور اصلی')
ON CONFLICT DO NOTHING;

INSERT INTO sensors (unit_id, tag, variable_name, unit_of_measure, protocol, min_value, max_value, nominal_value)
SELECT u.id, s.tag, s.variable_name, s.unit_of_measure, 'OPC-UA', s.min_value, s.max_value, s.nominal_value
FROM (VALUES
    ('reactor_temp_c',        'Temperature',      'C',      150, 350, 250),
    ('reactor_pressure_bar',  'Pressure',         'bar',    10,  40,  25),
    ('feed_flow_m3h',         'Flow',             'm3/h',   100, 500, 300),
    ('tank_level_percent',    'Level',            '%',      20,  85,  50),
    ('ethylene_conc_percent', 'GasComposition',   '%',      12,  25,  18),
    ('compressor_rpm',        'RPM',              'rpm',    1200, 1800, 1500)
) AS s(tag, variable_name, unit_of_measure, min_value, max_value, nominal_value)
CROSS JOIN (SELECT id FROM units WHERE name = 'Olefin Unit 1' LIMIT 1) AS u
ON CONFLICT (tag) DO NOTHING;
