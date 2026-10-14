"""Application settings, loaded from environment variables and `.env`."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Auto CRM API"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auto_crm"

    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Service key for automations (n8n). Empty disables API-key auth.
    automation_api_key: str = ""

    cors_origins: list[str] = ["http://localhost:3000"]

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    webhook_timeout_seconds: float = 10.0

    # Object storage (MinIO / any S3-compatible service) for uploaded images.
    s3_endpoint: str = "localhost:9100"  # host:port the API connects to
    s3_public_url: str = "http://localhost:9100"  # base URL browsers load images from
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "auto-crm"
    s3_secure: bool = False
    s3_region: str = "us-east-1"
    image_max_bytes: int = 5 * 1024 * 1024
    image_max_size_px: int = 512  # longest side after resizing

    # Outgoing email (SMTP). Mailpit catches everything in development.
    smtp_host: str = "localhost"
    smtp_port: int = 1026
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = False
    smtp_timeout_seconds: float = 10.0
    mail_from_email: str = "no-reply@autocrm.local"
    mail_from_name: str = "Auto CRM"

    frontend_url: str = "http://localhost:3000"  # for links in emails
    password_reset_expire_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
