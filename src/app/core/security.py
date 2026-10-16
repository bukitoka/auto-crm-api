import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

_password_hash = PasswordHash.recommended()  # Argon2


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _password_hash.verify(password, hashed_password)


def create_access_token(user_id: uuid.UUID) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {"sub": str(user_id), "exp": expires_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> uuid.UUID | None:
    """Return the user id stored in a token, or None if the token is invalid/expired."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if "purpose" in payload:  # e.g. a password-reset token is not a login token
            return None
        return uuid.UUID(payload["sub"])
    except jwt.PyJWTError, KeyError, ValueError:
        return None


_PASSWORD_RESET = "password_reset"


def _password_fingerprint(hashed_password: str) -> str:
    """Short hash of the current password hash. Changing the password changes it,
    which makes a reset link single-use without storing tokens in the database."""
    return hashlib.sha256(hashed_password.encode()).hexdigest()[:16]


def create_password_reset_token(user_id: uuid.UUID, hashed_password: str) -> str:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.password_reset_expire_minutes)
    payload = {
        "sub": str(user_id),
        "purpose": _PASSWORD_RESET,
        "pwd": _password_fingerprint(hashed_password),
        "exp": expires_at,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_password_reset_token(token: str) -> tuple[uuid.UUID, str] | None:
    """Return (user id, password fingerprint) from a reset token, or None if invalid."""
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("purpose") != _PASSWORD_RESET:
            return None
        return uuid.UUID(payload["sub"]), payload["pwd"]
    except jwt.PyJWTError, KeyError, ValueError:
        return None


def password_matches_fingerprint(hashed_password: str, fingerprint: str) -> bool:
    return secrets.compare_digest(_password_fingerprint(hashed_password), fingerprint)


def is_valid_api_key(api_key: str) -> bool:
    expected = settings.automation_api_key
    return bool(expected) and secrets.compare_digest(api_key, expected)


def generate_secret() -> str:
    return secrets.token_urlsafe(32)
