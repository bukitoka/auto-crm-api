from unittest.mock import AsyncMock

import pytest
from fastapi.security import HTTPAuthorizationCredentials

from app.core import security
from app.core.access import Scope, get_scope
from app.core.config import settings
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.modules.auth import dependencies
from app.modules.auth.schemas import LoginRequest
from app.modules.auth.service import AuthService
from tests.unit.conftest import make_user


@pytest.fixture
def service(session: AsyncMock) -> AuthService:
    service = AuthService(session)
    service.user_repo = AsyncMock()
    service.users = AsyncMock()
    return service


@pytest.fixture
def api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(settings, "automation_api_key", "unit-test-key")
    return "unit-test-key"


def _bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


async def test_login_returns_a_token_for_valid_credentials(service: AuthService) -> None:
    user = make_user(hashed_password=security.hash_password("password123"))
    service.user_repo.get_by_email.return_value = user

    result = await service.login(LoginRequest(email="user@example.com", password="password123"))

    assert result.token_type == "bearer"
    assert security.decode_access_token(result.access_token) == user.id


async def test_login_with_wrong_password_fails(service: AuthService) -> None:
    service.user_repo.get_by_email.return_value = make_user(
        hashed_password=security.hash_password("password123")
    )

    with pytest.raises(AuthenticationError, match="Incorrect email or password"):
        await service.login(LoginRequest(email="user@example.com", password="nope-nope"))


async def test_login_with_unknown_email_fails(service: AuthService) -> None:
    service.user_repo.get_by_email.return_value = None

    with pytest.raises(AuthenticationError, match="Incorrect email or password"):
        await service.login(LoginRequest(email="ghost@example.com", password="password123"))


async def test_login_of_disabled_user_fails(service: AuthService) -> None:
    service.user_repo.get_by_email.return_value = make_user(
        hashed_password=security.hash_password("password123"), is_active=False
    )

    with pytest.raises(AuthenticationError, match="disabled"):
        await service.login(LoginRequest(email="user@example.com", password="password123"))


async def test_user_from_token_returns_the_user(service: AuthService) -> None:
    user = make_user()
    service.user_repo.get.return_value = user

    assert await service.user_from_token(security.create_access_token(user.id)) is user


@pytest.mark.parametrize("problem", ["invalid-token", "unknown-user", "inactive-user"])
async def test_user_from_token_rejects_bad_tokens_and_users(
    service: AuthService, problem: str
) -> None:
    user = make_user(is_active=problem != "inactive-user")
    service.user_repo.get.return_value = None if problem == "unknown-user" else user
    token = "garbage" if problem == "invalid-token" else security.create_access_token(user.id)

    with pytest.raises(AuthenticationError, match="Invalid or expired token"):
        await service.user_from_token(token)


async def test_service_account_comes_from_user_service(service: AuthService) -> None:
    account = make_user(email="automation@auto-crm.local")
    service.users.get_or_create_service_account.return_value = account

    assert await service.service_account() is account


async def test_valid_api_key_authenticates_as_service_account(
    service: AuthService, session: AsyncMock, api_key: str
) -> None:
    account = make_user(email="automation@auto-crm.local")
    service.users.get_or_create_service_account.return_value = account

    user = await dependencies.get_current_user(service, session, bearer=None, api_key=api_key)

    assert user is account


async def test_invalid_api_key_is_rejected_even_with_a_valid_jwt(
    service: AuthService, session: AsyncMock, api_key: str
) -> None:
    token = security.create_access_token(make_user().id)

    with pytest.raises(AuthenticationError, match="Invalid API key"):
        await dependencies.get_current_user(
            service, session, bearer=_bearer(token), api_key="wrong"
        )


async def test_service_account_stays_unscoped(
    service: AuthService, session: AsyncMock, api_key: str
) -> None:
    service.users.get_or_create_service_account.return_value = make_user()

    await dependencies.get_current_user(service, session, bearer=None, api_key=api_key)

    assert get_scope(session) is None


async def test_admin_token_scopes_the_session_to_their_records(
    service: AuthService, session: AsyncMock
) -> None:
    user = make_user()
    service.user_repo.get.return_value = user
    token = security.create_access_token(user.id)

    result = await dependencies.get_current_user(
        service, session, bearer=_bearer(token), api_key=None
    )

    assert result is user
    assert get_scope(session) == Scope(owner_id=user.id)


async def test_super_admin_token_makes_the_session_read_only(
    service: AuthService, session: AsyncMock
) -> None:
    root = make_user(is_super_admin=True)
    service.user_repo.get.return_value = root
    token = security.create_access_token(root.id)

    await dependencies.get_current_user(service, session, bearer=_bearer(token), api_key=None)

    assert get_scope(session) == Scope(read_only=True)


async def test_no_credentials_is_unauthenticated(service: AuthService, session: AsyncMock) -> None:
    with pytest.raises(AuthenticationError, match="Not authenticated"):
        await dependencies.get_current_user(service, session, bearer=None, api_key=None)


async def test_working_user_allows_admins_and_rejects_the_super_admin() -> None:
    admin = make_user()
    assert await dependencies.require_working_user(admin) is admin

    with pytest.raises(PermissionDeniedError, match="view data but not change"):
        await dependencies.require_working_user(make_user(is_super_admin=True))


async def test_super_admin_guard_rejects_admins() -> None:
    root = make_user(is_super_admin=True)
    assert await dependencies.require_super_admin(root) is root

    with pytest.raises(PermissionDeniedError, match="Only the super admin"):
        await dependencies.require_super_admin(make_user())


async def test_require_api_key_accepts_the_configured_key(
    service: AuthService, api_key: str
) -> None:
    account = make_user(email="automation@auto-crm.local")
    service.users.get_or_create_service_account.return_value = account

    assert await dependencies.require_api_key(service, api_key=api_key) is account


@pytest.mark.parametrize("sent_key", [None, "wrong"])
async def test_require_api_key_rejects_missing_or_wrong_keys(
    service: AuthService, api_key: str, sent_key: str | None
) -> None:
    with pytest.raises(AuthenticationError, match="valid X-API-Key"):
        await dependencies.require_api_key(service, api_key=sent_key)
