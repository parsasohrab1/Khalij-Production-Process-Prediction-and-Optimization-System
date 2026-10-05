-- ==========================================================================
-- Khalij POS - Initial PostgreSQL schema (transactional data)
-- Per R-GEN-02, FR-ALERT-02, R-GEN-04 of the SRS document
-- ==========================================================================

-- Separate database for MLflow (model registry) to keep it apart from transactional data
SELECT 'CREATE DATABASE mlflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'mlflow')
\gexec

-- ---------------------------------------------------------------------
-- Operators and system users
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS operators (
    id              SERIAL PRIMARY KEY,
    employee_code   VARCHAR(32) UNIQUE NOT NULL,
    full_name       VARCHAR(128) NOT NULL,
    password_hash   VARCHAR(256) NOT NULL,
    otp_secret      VARCHAR(64),                               -- Base32 secret for TOTP (NFR-SEC-01)
    role            VARCHAR(32) NOT NULL DEFAULT 'operator', -- operator | supervisor | admin
    shift           VARCHAR(16),                              -- morning | evening | night
    two_factor_enabled BOOLEAN NOT NULL DEFAULT TRUE,          -- NFR-SEC-01
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------
-- Definition of units and sensors (olefin / polymerization)
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
-- Alerts (FR-ALERT-01 / FR-ALERT-02)
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
-- End-of-shift energy optimization report (R-GEN-04)
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
-- Optimization recommendations issued by the Recommender module (FR-ML-03)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS optimization_recommendations (
    id                  BIGSERIAL PRIMARY KEY,
    unit_id             INTEGER REFERENCES units(id),
    variable_name       VARCHAR(64) NOT NULL,
    current_value       DOUBLE PRECISION,
    recommended_value   DOUBLE PRECISION,
    expected_efficiency_gain DOUBLE PRECISION,
    model_run_id        VARCHAR(64), -- MLflow run id
    recommendation_json JSONB,                         -- complete multivariable recommendation (phase 4)
    expected_efficiency DOUBLE PRECISION,              -- estimated efficiency after application
    actual_efficiency   DOUBLE PRECISION,              -- actual measured efficiency
    efficiency_error    DOUBLE PRECISION,              -- actual - expected
    whatif_snapshot     JSONB,                         -- What-if result before application
    feedback_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    applied              BOOLEAN NOT NULL DEFAULT FALSE,
    applied_by           INTEGER REFERENCES operators(id)
);

-- Optimization closed-loop events (phase 4)
CREATE TABLE IF NOT EXISTS optimization_feedback_events (
    id                  BIGSERIAL PRIMARY KEY,
    recommendation_id   BIGINT REFERENCES optimization_recommendations(id) ON DELETE CASCADE,
    unit_id             INTEGER,
    event_type          VARCHAR(32) NOT NULL,  -- applied | feedback | rejected
    payload             JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    operator_id         INTEGER REFERENCES operators(id)
);

-- ---------------------------------------------------------------------
-- Demo operator for login testing (NFR-SEC-01) - default password: ChangeMe123!
-- ⚠️ Be sure to delete/update this record after deployment in the operational environment.
-- ---------------------------------------------------------------------
INSERT INTO operators (employee_code, full_name, password_hash, otp_secret, role, shift)
VALUES (
    'demo-admin',
    'Demo operator',
    '$2b$12$dTFM.AIRyaHlm8xioKQLnegLWMo1PT8AwDuuZHNO6SWHTD5QFUyyS',
    '3MYXLVCKBIRJUTD6',
    'admin',
    'morning'
)
ON CONFLICT (employee_code) DO NOTHING;

-- Sample roles for phase 6 RBAC testing (same password ChangeMe123!)
INSERT INTO operators (employee_code, full_name, password_hash, otp_secret, role, shift)
VALUES
    (
        'demo-operator',
        'Line operator',
        '$2b$12$dTFM.AIRyaHlm8xioKQLnegLWMo1PT8AwDuuZHNO6SWHTD5QFUyyS',
        '3MYXLVCKBIRJUTD6',
        'operator',
        'morning'
    ),
    (
        'demo-supervisor',
        'Shift supervisor',
        '$2b$12$dTFM.AIRyaHlm8xioKQLnegLWMo1PT8AwDuuZHNO6SWHTD5QFUyyS',
        '3MYXLVCKBIRJUTD6',
        'supervisor',
        'evening'
    )
ON CONFLICT (employee_code) DO NOTHING;

-- ---------------------------------------------------------------------
-- Security Audit Trail (phase 6)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      VARCHAR(64) NOT NULL,
    actor_code      VARCHAR(32),
    actor_role      VARCHAR(32),
    resource        VARCHAR(128),
    action          VARCHAR(64) NOT NULL,
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    ip_address      VARCHAR(64),
    user_agent      TEXT,
    details         JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_events (actor_code);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_events (event_type);

-- ---------------------------------------------------------------------
-- Initial sample data (default unit and sensors per FR-DATA-02)
-- ---------------------------------------------------------------------
INSERT INTO units (name, unit_type, description)
VALUES ('Olefin Unit 1', 'olefin', 'Olefin Unit 1 - main reactor')
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
