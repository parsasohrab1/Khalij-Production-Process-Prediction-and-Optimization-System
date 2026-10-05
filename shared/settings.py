"""Shared configuration of all services, values are read from environment variables (.env)."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = Field(default="development", alias="ENVIRONMENT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # PostgreSQL
    postgres_dsn: str = Field(
        default="postgresql+psycopg2://khalij_admin:change_me@postgres:5432/khalij_pos",
        alias="POSTGRES_DSN",
    )

    # InfluxDB
    influxdb_url: str = Field(default="http://influxdb:8086", alias="INFLUXDB_URL")
    influxdb_org: str = Field(default="khalij-holding", alias="INFLUXDB_ORG")
    influxdb_bucket: str = Field(default="process_sensors", alias="INFLUXDB_BUCKET")
    influxdb_token: str = Field(default="", alias="INFLUXDB_TOKEN")

    # Redis
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # Kafka
    kafka_bootstrap_servers: str = Field(default="kafka:9092", alias="KAFKA_BOOTSTRAP_SERVERS")
    kafka_topic_raw_sensors: str = Field(default="raw-sensor-data", alias="KAFKA_TOPIC_RAW_SENSORS")
    kafka_topic_processed_sensors: str = Field(
        default="processed-sensor-data", alias="KAFKA_TOPIC_PROCESSED_SENSORS"
    )
    kafka_topic_predictions: str = Field(default="process-predictions", alias="KAFKA_TOPIC_PREDICTIONS")
    kafka_topic_alerts: str = Field(default="process-alerts", alias="KAFKA_TOPIC_ALERTS")
    kafka_topic_raw_dlq: str = Field(default="raw-sensor-data-dlq", alias="KAFKA_TOPIC_RAW_DLQ")
    kafka_topic_processed_dlq: str = Field(
        default="processed-sensor-data-dlq", alias="KAFKA_TOPIC_PROCESSED_DLQ"
    )
    kafka_consumer_group: str = Field(default="khalij-pos", alias="KAFKA_CONSUMER_GROUP")

    # InfluxDB long-term / downsampling (phase 2 / R-GEN-02)
    influxdb_bucket_downsampled: str = Field(
        default="process_sensors_1m", alias="INFLUXDB_BUCKET_DOWNSAMPLED"
    )
    influxdb_hot_retention: str = Field(default="30d", alias="INFLUXDB_HOT_RETENTION")
    # MLflow
    mlflow_tracking_uri: str = Field(default="http://mlflow:5000", alias="MLFLOW_TRACKING_URI")

    # Prediction / Optimization (FR-ML-01, FR-ML-02)
    prediction_horizon_seconds: int = Field(default=60, alias="PREDICTION_HORIZON_SECONDS")
    critical_deviation_percent: float = Field(default=5.0, alias="CRITICAL_DEVIATION_PERCENT")
    reactor_nominal_temp_c: float = Field(default=250.0, alias="REACTOR_NOMINAL_TEMP_C")

    # Alerting (FR-ALERT-01)
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from_address: str = Field(default="", alias="SMTP_FROM_ADDRESS")
    smtp_to_addresses: str = Field(default="", alias="SMTP_TO_ADDRESSES")

    # Security (NFR-SEC-01, NFR-SEC-02) + phase 6 hardening
    jwt_secret_key: str = Field(default="dev-secret-change-me", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=30, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    two_factor_required: bool = Field(default=True, alias="TWO_FACTOR_REQUIRED")
    cors_allow_origins: str = Field(default="*", alias="CORS_ALLOW_ORIGINS")
    login_max_failures: int = Field(default=5, alias="LOGIN_MAX_FAILURES")
    login_lockout_seconds: int = Field(default=900, alias="LOGIN_LOCKOUT_SECONDS")
    rate_limit_login_per_minute: int = Field(default=10, alias="RATE_LIMIT_LOGIN_PER_MINUTE")
    rate_limit_api_per_minute: int = Field(default=120, alias="RATE_LIMIT_API_PER_MINUTE")
    enforce_production_secrets: bool = Field(default=False, alias="ENFORCE_PRODUCTION_SECRETS")
    internal_api_key: str = Field(default="", alias="INTERNAL_API_KEY")
    data_encryption_key: str = Field(default="", alias="DATA_ENCRYPTION_KEY")

    # Service ports
    api_gateway_port: int = Field(default=8000, alias="API_GATEWAY_PORT")
    data_ingestion_port: int = Field(default=8001, alias="DATA_INGESTION_PORT")
    preprocessing_port: int = Field(default=8002, alias="PREPROCESSING_PORT")
    prediction_port: int = Field(default=8003, alias="PREDICTION_PORT")
    alerting_port: int = Field(default=8004, alias="ALERTING_PORT")


@lru_cache
def get_settings() -> Settings:
    return Settings()
