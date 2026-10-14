import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security
from app.core.config import settings


def test_hash_password_does_not_store_the_plain_password() -> None:
    hashed = security.hash_password("s3cret-password")

    assert hashed != "s3cret-password"
    assert hashed.startswith("$argon2")


def test_verify_password_accepts_the_right_password_only() -> None:
    hashed = security.hash_password("s3cret-password")

    assert security.verify_password("s3cret-password", hashed) is True
    assert security.verify_password("wrong-password", hashed) is False


def test_access_token_round_trip_returns_the_user_id() -> None:
    user_id = uuid.uuid7()

    token = security.create_access_token(user_id)

    assert security.decode_access_token(token) == user_id


def test_access_token_expires_after_the_configured_minutes() -> None:
    token = security.create_access_token(uuid.uuid7())

    payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    expires_at = datetime.fromtimestamp(payload["exp"], UTC)
    expected = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    assert abs(expires_at - expected) < timedelta(seconds=5)


def _token(payload: dict, secret: str = settings.jwt_secret_key) -> str:
    return jwt.encode(payload, secret, algorithm=settings.jwt_algorithm)


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("not-a-jwt", id="garbage"),
        pytest.param(
            _token({"sub": str(uuid.uuid7()), "exp": datetime.now(UTC) - timedelta(minutes=1)}),
            id="expired",
        ),
        pytest.param(
            _token({"sub": str(uuid.uuid7())}, secret="a-different-secret-that-is-long-enough"),
            id="wrong-secret",
        ),
        pytest.param(_token({"exp": datetime.now(UTC) + timedelta(minutes=5)}), id="missing-sub"),
        pytest.param(_token({"sub": "not-a-uuid"}), id="sub-not-a-uuid"),
    ],
)
def test_decode_access_token_returns_none_for_invalid_tokens(token: str) -> None:
    assert security.decode_access_token(token) is None


def test_is_valid_api_key_compares_with_the_configured_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "automation_api_key", "the-key")

    assert security.is_valid_api_key("the-key") is True
    assert security.is_valid_api_key("another-key") is False


def test_api_key_auth_is_disabled_when_no_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "automation_api_key", "")

    assert security.is_valid_api_key("") is False


def test_generate_secret_is_random_and_long_enough() -> None:
    first, second = security.generate_secret(), security.generate_secret()

    assert first != second
    assert len(first) >= 32
