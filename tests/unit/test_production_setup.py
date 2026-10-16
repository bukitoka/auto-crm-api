from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from brevo import AsyncBrevo
from brevo.core.api_error import ApiError
from fastapi import Request
from pydantic import ValidationError

from app.core.config import Settings, normalize_database_url
from app.core.email import BrevoMailer, Mail
from app.core.exceptions import EmailDeliveryError
from app.core.rate_limit import RateLimiter, TooManyRequestsError
from app.core.storage import Storage

SECRET = "x" * 40
PRODUCTION: dict[str, Any] = {
    "environment": "production",
    "jwt_secret_key": SECRET,
    "automation_api_key": SECRET,
    "s3_access_key": "nak_real",
    "s3_secret_key": "nsk_real",
    "mail_from_email": "crm@example.com",
    "brevo_api_key": "xkeysib-real",
    "cors_origins": ["https://crm.example.com"],
    "frontend_url": "https://crm.example.com",
}


def test_neon_url_is_made_asyncpg_friendly() -> None:
    url = normalize_database_url(
        "postgresql://u:p@ep-x-pooler.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://u:p@ep-x-pooler.neon.tech/neondb?ssl=require"


def test_plain_local_url_is_untouched() -> None:
    url = "postgresql+asyncpg://postgres:postgres@localhost:5432/auto_crm"
    assert normalize_database_url(url) == url


def test_neon_aws_variable_names_are_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ENDPOINT_URL_S3", "https://bucket.storage.neon.tech")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "nak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nsk")
    monkeypatch.setenv("AWS_REGION", "ap-southeast-1")
    config = Settings(_env_file=None)
    assert config.s3_endpoint == "https://bucket.storage.neon.tech"
    assert (config.s3_access_key, config.s3_secret_key) == ("nak", "nsk")
    assert config.s3_region == "ap-southeast-1"


def test_storage_signs_urls_for_an_https_endpoint() -> None:
    config = Settings(
        _env_file=None,
        s3_endpoint="https://bucket.storage.neon.tech",
        s3_region="ap-southeast-1",
    )
    url = Storage(config).url("contacts/1/a.webp")
    assert url.startswith("https://bucket.storage.neon.tech/")


def test_production_accepts_a_complete_configuration() -> None:
    assert Settings(_env_file=None, **PRODUCTION).is_production


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"jwt_secret_key": "change-me"}, "JWT_SECRET_KEY"),
        ({"automation_api_key": ""}, "AUTOMATION_API_KEY"),
        ({"s3_secret_key": "minioadmin"}, "S3 credentials"),
        ({"brevo_api_key": ""}, "BREVO_API_KEY"),
        ({"mail_from_email": "no-reply@autocrm.local"}, "MAIL_FROM_EMAIL"),
        ({"cors_origins": ["http://localhost:3000"]}, "CORS_ORIGINS"),
        ({"frontend_url": "http://crm.example.com"}, "FRONTEND_URL"),
    ],
)
def test_production_rejects_unsafe_settings(override: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **{**PRODUCTION, **override})


def brevo_mailer(**settings_override: Any) -> BrevoMailer:
    config = Settings(_env_file=None, brevo_api_key="key", **settings_override)
    return BrevoMailer(config)


async def test_brevo_mailer_sends_through_the_sdk() -> None:
    mailer = brevo_mailer(mail_from_email="crm@example.com", mail_from_name="Auto CRM")
    mailer._client = cast(
        AsyncBrevo,
        SimpleNamespace(transactional_emails=SimpleNamespace(send_transac_email=AsyncMock())),
    )
    await mailer.send(
        Mail(
            to="Jane Doe <jane@example.com>",
            subject="Hello",
            text="Hi",
            reply_to="Sam <sam@example.com>",
            from_name="Sam via Auto CRM",
        )
    )
    call = mailer._client.transactional_emails.send_transac_email.await_args.kwargs
    assert call["sender"].email == "crm@example.com"
    assert call["sender"].name == "Sam via Auto CRM"
    assert (call["to"][0].email, call["to"][0].name) == ("jane@example.com", "Jane Doe")
    assert call["reply_to"].email == "sam@example.com"
    assert call["subject"] == "Hello"


async def test_brevo_failures_become_delivery_errors() -> None:
    mailer = brevo_mailer()
    mailer._client = cast(
        AsyncBrevo,
        SimpleNamespace(
            transactional_emails=SimpleNamespace(
                send_transac_email=AsyncMock(side_effect=ApiError(status_code=401, body={}))
            )
        ),
    )
    with pytest.raises(EmailDeliveryError):
        await mailer.send(Mail(to="jane@example.com", subject="Hi", text="Hi"))


def request_from(host: str) -> Request:
    return cast(Request, SimpleNamespace(client=SimpleNamespace(host=host)))


async def test_rate_limiter_blocks_after_the_limit() -> None:
    limiter = RateLimiter("t", lambda: 2, 60)
    request = request_from("1.2.3.4")
    await limiter(request)
    await limiter(request)
    with pytest.raises(TooManyRequestsError):
        await limiter(request)
    await limiter(request_from("5.6.7.8"))


async def test_rate_limiter_with_zero_limit_is_off() -> None:
    limiter = RateLimiter("t", lambda: 0, 60)
    request = request_from("1.2.3.4")
    for _ in range(5):
        await limiter(request)
