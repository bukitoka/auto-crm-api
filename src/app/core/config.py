from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

_PLACEHOLDER_SECRETS = {"", "change-me", "minioadmin"}
_MIN_SECRET_LENGTH = 32


def normalize_database_url(value: str) -> str:
    """Accept the URL as Neon prints it (`postgresql://...?sslmode=require&channel_binding=require`)
    and turn it into one asyncpg understands."""
    url = make_url(value)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    if url.drivername != "postgresql+asyncpg":
        return value
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)  # asyncpg has no equivalent; TLS still protects the link
    if sslmode and sslmode != "disable" and "ssl" not in query:
        query["ssl"] = "require" if sslmode in {"require", "prefer", "allow"} else sslmode
    return url.set(query=query).render_as_string(hide_password=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "Auto CRM API"
    api_prefix: str = "/api/v1"
    environment: Literal["development", "production"] = "development"

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/auto_crm"
    # Neon: the pooled URL serves the app, the direct (non "-pooler") URL runs migrations.
    database_direct_url: str = ""
    db_pool_size: int = 5
    db_max_overflow: int = 5

    jwt_secret_key: str = "change-me"
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = 60 * 24

    # Service key for automations (n8n). Empty disables API-key auth.
    automation_api_key: str = ""

    cors_origins: list[str] = ["http://localhost:3000"]
    allowed_hosts: list[str] = ["*"]

    # Failed-login throttling, per client IP. 0 turns a limit off.
    login_attempts_per_minute: int = 10
    password_reset_requests_per_hour: int = 5

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    webhook_timeout_seconds: float = 10.0

    # Object storage for uploaded images: MinIO locally, Neon object storage in production.
    # The AWS_* names are what Neon shows in its console, so they work unchanged.
    # S3_ENDPOINT is `host:port` or a full URL (`https://...`).
    s3_endpoint: str = Field(
        "localhost:9100", validation_alias=AliasChoices("s3_endpoint", "aws_endpoint_url_s3")
    )
    # Base URL browsers load images from. Empty means the endpoint itself.
    s3_public_url: str = ""
    s3_access_key: str = Field(
        "minioadmin", validation_alias=AliasChoices("s3_access_key", "aws_access_key_id")
    )
    s3_secret_key: str = Field(
        "minioadmin", validation_alias=AliasChoices("s3_secret_key", "aws_secret_access_key")
    )
    s3_bucket: str = "auto-crm"
    s3_secure: bool = False  # only used when S3_ENDPOINT has no scheme
    s3_region: str = Field("us-east-1", validation_alias=AliasChoices("s3_region", "aws_region"))
    s3_create_bucket: bool = True  # turn off when the bucket already exists (Neon)
    image_max_bytes: int = 5 * 1024 * 1024
    image_max_size_px: int = 512  # longest side after resizing

    # Outgoing email goes through the Brevo SDK. Without a key, sending fails with a 503.
    brevo_api_key: str = ""
    brevo_timeout_seconds: float = 10.0
    mail_from_email: str = "no-reply@autocrm.local"
    mail_from_name: str = "Auto CRM"

    frontend_url: str = "http://localhost:3000"  # for links in emails
    password_reset_expire_minutes: int = 30

    @field_validator("database_url", "database_direct_url")
    @classmethod
    def _asyncpg_url(cls, value: str) -> str:
        return normalize_database_url(value) if value else value

    @model_validator(mode="after")
    def _require_real_secrets_in_production(self) -> Settings:
        if self.environment != "production":
            return self
        problems = []
        if (
            self.jwt_secret_key in _PLACEHOLDER_SECRETS
            or len(self.jwt_secret_key) < _MIN_SECRET_LENGTH
        ):
            problems.append(
                f"JWT_SECRET_KEY must be a random value of {_MIN_SECRET_LENGTH}+ characters"
            )
        key = self.automation_api_key
        if key in _PLACEHOLDER_SECRETS or len(key) < _MIN_SECRET_LENGTH:
            problems.append(
                f"AUTOMATION_API_KEY must be a random value of {_MIN_SECRET_LENGTH}+ characters"
            )
        if "minioadmin" in {self.s3_access_key, self.s3_secret_key}:
            problems.append("S3 credentials are still the MinIO defaults")
        if not self.brevo_api_key:
            problems.append("BREVO_API_KEY is required")
        if self.mail_from_email.endswith(".local"):
            problems.append("MAIL_FROM_EMAIL must be a sender verified in Brevo")
        if any(
            urlsplit(origin).hostname in {"localhost", "127.0.0.1"} for origin in self.cors_origins
        ):
            problems.append("CORS_ORIGINS must not contain localhost")
        if not self.frontend_url.startswith("https://"):
            problems.append("FRONTEND_URL must be an https URL")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def migration_database_url(self) -> str:
        return self.database_direct_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
