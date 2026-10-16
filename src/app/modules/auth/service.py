import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.email import Mailer, get_mailer
from app.core.exceptions import AppError, AuthenticationError, BadRequestError
from app.core.security import (
    create_access_token,
    create_password_reset_token,
    decode_access_token,
    decode_password_reset_token,
    hash_password,
    password_matches_fingerprint,
    verify_password,
)
from app.modules.auth.emails import password_reset_mail
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SetupStatus,
    TokenResponse,
)
from app.modules.users.models import User
from app.modules.users.repository import UserRepository
from app.modules.users.service import SERVICE_ACCOUNT_EMAIL, UserService

logger = logging.getLogger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession, mailer: Mailer | None = None) -> None:
        self.session = session
        self.users = UserService(session)
        self.user_repo = UserRepository(session)
        self.mailer = mailer or get_mailer()

    async def register(self, data: RegisterRequest) -> User:
        return await self.users.create(
            email=data.email, password=data.password, full_name=data.full_name
        )

    async def setup_status(self) -> SetupStatus:
        return SetupStatus(needs_setup=not await self.user_repo.super_admin_exists())

    async def setup(self, data: RegisterRequest) -> User:
        return await self.users.setup(
            email=data.email, password=data.password, full_name=data.full_name
        )

    async def login(self, data: LoginRequest) -> TokenResponse:
        user = await self.user_repo.get_by_email(data.email)
        if user is None or not verify_password(data.password, user.hashed_password):
            raise AuthenticationError("Incorrect email or password")
        if not user.is_active:
            raise AuthenticationError("This account is disabled")
        return TokenResponse(access_token=create_access_token(user.id))

    async def user_from_token(self, token: str) -> User:
        user_id = decode_access_token(token)
        user = await self.user_repo.get(user_id) if user_id else None
        if user is None or not user.is_active:
            raise AuthenticationError("Invalid or expired token")
        return user

    async def request_password_reset(self, data: ForgotPasswordRequest) -> None:
        """Email a reset link if the account exists.

        The response is the same whether or not the email is registered (and even if
        sending fails), so this endpoint cannot be used to find out who has an account.
        """
        user = await self.user_repo.get_by_email(data.email)
        if user is None or not user.is_active or user.email == SERVICE_ACCOUNT_EMAIL:
            return
        token = create_password_reset_token(user.id, user.hashed_password)
        try:
            await self.mailer.send(password_reset_mail(user, token))
        except AppError:
            logger.warning("Password reset email for %s was not sent", user.email)

    async def reset_password(self, data: ResetPasswordRequest) -> None:
        decoded = decode_password_reset_token(data.token)
        user = await self.user_repo.get(decoded[0]) if decoded else None
        if (
            decoded is None
            or user is None
            or not user.is_active
            or not password_matches_fingerprint(user.hashed_password, decoded[1])
        ):
            raise BadRequestError("This reset link is invalid or has expired")
        user.hashed_password = hash_password(data.password)
        await self.session.commit()

    async def service_account(self) -> User:
        return await self.users.get_or_create_service_account()
