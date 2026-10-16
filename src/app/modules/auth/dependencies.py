"""Authentication dependencies used by every protected route.

A request is authenticated by either:
- `Authorization: Bearer <jwt>` (people using the web app), or
- `X-API-Key: <AUTOMATION_API_KEY>` (n8n, acting as the service account).
"""

from typing import Annotated

from fastapi import Depends
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.access import scope_for, set_scope
from app.core.database import SessionDep
from app.core.email import MailerDep
from app.core.exceptions import AuthenticationError, PermissionDeniedError
from app.core.security import is_valid_api_key
from app.modules.auth.service import AuthService
from app.modules.users.models import User

bearer_scheme = HTTPBearer(auto_error=False)
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_auth_service(session: SessionDep, mailer: MailerDep) -> AuthService:
    return AuthService(session, mailer)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    service: AuthServiceDep,
    session: SessionDep,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    api_key: Annotated[str | None, Depends(api_key_scheme)],
) -> User:
    """Authenticate the request and scope the session to what this user may touch."""
    if api_key is not None:
        if not is_valid_api_key(api_key):
            raise AuthenticationError("Invalid API key")
        return await service.service_account()
    if bearer is None:
        raise AuthenticationError()
    user = await service.user_from_token(bearer.credentials)
    set_scope(session, scope_for(user))
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_working_user(user: CurrentUser) -> User:
    if user.is_super_admin:
        raise PermissionDeniedError("The super admin can view data but not change it")
    return user


async def require_super_admin(user: CurrentUser) -> User:
    if not user.is_super_admin:
        raise PermissionDeniedError("Only the super admin can do this")
    return user


# Admins and the automation service account: whoever does CRM work.
WorkingUser = Annotated[User, Depends(require_working_user)]
SuperAdminUser = Annotated[User, Depends(require_super_admin)]


async def require_api_key(
    service: AuthServiceDep,
    api_key: Annotated[str | None, Depends(api_key_scheme)],
) -> User:
    """Only the automation API key is accepted (no JWT)."""
    if api_key is None or not is_valid_api_key(api_key):
        raise AuthenticationError("A valid X-API-Key header is required")
    return await service.service_account()


ServiceAccount = Annotated[User, Depends(require_api_key)]
